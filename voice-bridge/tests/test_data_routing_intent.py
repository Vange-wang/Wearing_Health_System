"""DATA 路由意图识别回归：当前数值查询与健康知识问题必须分流。"""

import asyncio

import pytest

from app.health import HealthDataStore
from app.llm import LightweightLLM
from app.pipeline import StreamingPipeline, TimingRecord
from app.router import DATA, LIGHTWEIGHT, RAG, Router
from app.tts import wrap_pcm_as_wav


DATA_QUERIES = [
    "心率多少", "心率是多少", "心率怎么样", "心率如何", "心率咋样",
    "血氧多少", "血氧是多少", "血氧怎么样", "血氧如何", "血氧咋样",
    "心率血氧", "心率跟血氧", "心率和血氧",
    "测一下心率", "测一下血氧", "查一下心率", "查一下血氧",
    "血压多少", "血压是多少",
]


def make_router() -> Router:
    return Router(
        tool_keywords=["帮我查", "查一下", "看看", "是什么", "怎么样", "如何"],
        skill_keywords=[],
        data_keywords=DATA_QUERIES,
        asr_normalize={"血阳": "血氧", "雪阳": "血氧", "学养": "血氧", "学样": "血氧"},
    )


@pytest.mark.parametrize(
    "text",
    [
        "我的心率多少",
        "血氧是多少",
        "我的心率和血氧是多少",
        "心率跟血氧分别是多少",
        "查一下心率",
        "血压多少",
    ],
)
def test_current_value_queries_use_data_template(text):
    assert make_router().route(text) == DATA


@pytest.mark.parametrize(
    "text",
    [
        "心率的正常范围是多少",
        "正常血压是多少",
        "心率为什么突然变快",
        "血氧太高",
        "血氧太高怎么办",
        "如果一个人的血氧太低怎么办",
        "如果一个人的心率太高怎么办",
        "心率跟血氧是什么关系",
        "血氧仪怎么选",
        "帮我看看心率",
    ],
)
def test_health_knowledge_questions_do_not_use_data_template(text):
    assert make_router().route(text, rag_hit=False) == LIGHTWEIGHT


def test_rag_hit_precedes_health_domain_lightweight_fallback():
    assert make_router().route("心率跟血氧是什么关系", rag_hit=True) == RAG


@pytest.mark.parametrize("raw", ["我的血阳是多少", "雪阳是多少"])
def test_asr_normalization_preserves_direct_data_query(raw):
    router = make_router()
    normalized = router.normalize_asr(raw)
    assert "血氧是多少" in normalized
    assert router.route(normalized) == DATA


def test_data_followup_keeps_previous_data_route():
    router = make_router()
    assert router.route("我的心率是多少") == DATA
    assert router.route("你再看一下") == DATA


def test_greeting_breaks_previous_data_route():
    """普通问候是新话题，不能继承上一轮 DATA 模板。"""
    router = make_router()
    assert router.route("心率多少") == DATA
    assert router.route("你好") == LIGHTWEIGHT


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class NeverHermes:
    name = "hermes"
    stats = {}

    def stream_chat(self, user_text):
        raise AssertionError(f"unexpected Hermes route: {user_text}")


class CapturingTTS:
    def __init__(self) -> None:
        self.texts = []

    async def synthesize(self, text):
        self.texts.append(text)
        return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)


class CapturingLightweight(LightweightLLM):
    def __init__(self, profile):
        super().__init__("sk-test", "http://127.0.0.1:1", "deepseek-chat", profile)
        self.prompts = []

    def stream_chat(self, user_text):
        self.prompts.append(self._system_prompt(user_text))
        return iter(["语义回答完成。"])


def make_pipeline(tmp_path, store):
    profile = tmp_path / "USER.md"
    profile.write_text("用户画像", encoding="utf-8")
    lightweight = CapturingLightweight(profile)
    tts = CapturingTTS()
    pipeline = StreamingPipeline(
        asr=None,
        llm=NeverHermes(),
        tts=tts,
        vad=None,
        lightweight_llm=lightweight,
        router=make_router(),
        health=store,
        data_stale_seconds=60,
        sentence_gap_ms=0,
        tts_workers=1,
    )
    return pipeline, lightweight, tts


def run_text(pipeline, text):
    timing = TimingRecord()

    async def collect():
        return [frame async for frame in pipeline.run_text(text, timing=timing)]

    frames = asyncio.run(collect())
    assert frames
    return timing


def test_pipeline_direct_data_queries_use_fresh_template_values(tmp_path):
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=76, spo2=98, seq=1, flags=0x03, quality=1.0)
    pipeline, lightweight, tts = make_pipeline(tmp_path, store)
    try:
        for text in [
            "我的心率多少",
            "心率跟血氧",
            "你再看一下",
            "我的血阳是多少",
            "血压多少",
        ]:
            before = len(tts.texts)
            timing = run_text(pipeline, text)
            assert timing["route"] == DATA
            assert timing["llm_backend"] == "template"
            assert len(tts.texts) == before + 1

        assert "心率 76" in tts.texts[0]
        assert "血氧" not in tts.texts[0]
        assert "心率 76" in tts.texts[1]
        assert "血氧 98" in tts.texts[1]
        assert "心率 76" in tts.texts[2]
        assert "血氧 98" in tts.texts[2]
        assert "血氧 98" in tts.texts[3]
        assert "心率" not in tts.texts[3]
        assert "血压功能还没有接入" in tts.texts[4]
        assert lightweight.prompts == []
    finally:
        lightweight.close()


@pytest.mark.parametrize(
    "text",
    [
        "帮我看看心率",
        "心率的正常范围是多少",
        "心率为什么突然变快",
        "心率跟血氧是什么关系",
        "血氧仪怎么选",
    ],
)
def test_pipeline_health_semantic_questions_use_lightweight_with_fresh_context(
    tmp_path, text
):
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=76, spo2=98, seq=1, flags=0x03, quality=1.0)
    pipeline, lightweight, _ = make_pipeline(tmp_path, store)
    try:
        timing = run_text(pipeline, text)

        assert timing["route"] == LIGHTWEIGHT
        assert timing["llm_backend"] == "deepseek"
        assert "心率 76" in lightweight.prompts[-1]
        assert "血氧 98" in lightweight.prompts[-1]
    finally:
        lightweight.close()


def test_pipeline_stale_data_is_removed_from_both_semantic_and_data_paths(tmp_path):
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=76, spo2=98, seq=1, flags=0x03, quality=1.0)
    clock.advance(61)
    pipeline, lightweight, tts = make_pipeline(tmp_path, store)
    try:
        semantic = run_text(pipeline, "帮我看看心率")
        assert semantic["route"] == LIGHTWEIGHT
        assert "心率 76" not in lightweight.prompts[-1]
        assert "血氧 98" not in lightweight.prompts[-1]
        assert "暂无最新数据" in lightweight.prompts[-1]
        assert "不得猜测或编造数值" in lightweight.prompts[-1]

        direct = run_text(pipeline, "心率多少")
        assert direct["route"] == DATA
        assert "健康数据检测暂时中断" in tts.texts[-1]
        assert "76" not in tts.texts[-1]
        assert "98" not in tts.texts[-1]
    finally:
        lightweight.close()
