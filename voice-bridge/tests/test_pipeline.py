"""ISSUE-0013 跨路径上下文联动的 Pipeline 公共行为测试。"""

import asyncio
import time

import pytest

import app.pipeline as pipeline_module

from app.llm import LLMError
from app.pipeline import StreamingPipeline, TimingRecord
from app.router import Router
from app.tts import TTSError, wrap_pcm_as_wav


class CapturingLLM:
    name = "fake"
    stats = {}

    def __init__(self, replies=None):
        self.replies = list(replies or ["默认回答。"])
        self.calls = []

    def stream_chat(self, text):
        self.calls.append(text)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return iter([reply])


class CapturingTTS:
    def __init__(self):
        self.texts = []

    async def synthesize(self, text):
        self.texts.append(text)
        return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)


class CapturingRAG:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def search(self, text, top_k, score_threshold):
        self.calls.append(text)
        return list(self.results)


def make_pipeline(
    *, replies=None, rag=None, health=None, hermes=None, lightweight=None, tts=None
):
    hermes = hermes or CapturingLLM(replies)
    lightweight = lightweight or CapturingLLM(replies)
    tts = tts or CapturingTTS()
    router = Router(
        tool_keywords=["查天气"],
        skill_keywords=[],
        data_keywords=["心率多少", "血氧多少", "心率血氧"],
    )
    pipeline = StreamingPipeline(
        asr=None,
        llm=hermes,
        tts=tts,
        vad=None,
        lightweight_llm=lightweight,
        router=router,
        rag=rag,
        health=health,
        sentence_gap_ms=0,
        tts_workers=1,
        acknowledgements={"query": [b"ACK"]},
    )
    return pipeline, hermes, lightweight, tts


def run_text(pipeline, text):
    timing = TimingRecord()

    async def collect():
        return [frame async for frame in pipeline.run_text(text, timing=timing)]

    frames = asyncio.run(collect())
    assert frames
    return timing


def test_replay_reuses_last_reply_without_llm_or_rag():
    rag = CapturingRAG()
    pipeline, hermes, lightweight, tts = make_pipeline(
        replies=["上一轮完整回答。"], rag=rag
    )
    run_text(pipeline, "你好呀")
    before_calls = len(hermes.calls) + len(lightweight.calls)
    before_rag = len(rag.calls)

    timing = run_text(pipeline, "再说一遍")

    assert timing["route"] == "replay"
    assert timing["llm_backend"] == "replay"
    assert timing["comfort_sent"] is False
    assert tts.texts[-1] == "上一轮完整回答。"
    assert len(hermes.calls) + len(lightweight.calls) == before_calls
    assert len(rag.calls) == before_rag


def test_replay_without_snapshot_returns_fixed_local_text():
    pipeline, hermes, lightweight, tts = make_pipeline()

    timing = run_text(pipeline, "重新说一遍")

    assert timing["route"] == "replay"
    assert tts.texts == ["刚才没有可以重复的内容哦，先跟我说说话吧。"]
    assert hermes.calls == []
    assert lightweight.calls == []


def test_context_without_snapshot_returns_fixed_local_text():
    pipeline, hermes, lightweight, tts = make_pipeline()

    timing = run_text(pipeline, "刚才那个呢")

    assert timing["route"] == "context"
    assert tts.texts == ["我有点没跟上，你是指哪件事呀？"]
    assert hermes.calls == []
    assert lightweight.calls == []


def expected_context_prompt(user_text, reply_text, current_text):
    return (
        f"【上一轮】用户：{user_text}\n"
        f"小V：{reply_text[:500]}\n\n"
        f"【本轮】用户：{current_text}"
    )


def test_context_continues_lightweight_once_with_bounded_prefix():
    first_reply = "上" * 600
    pipeline, hermes, lightweight, _ = make_pipeline(
        replies=[first_reply, "上下文回答。"]
    )
    run_text(pipeline, "普通问题")

    timing = run_text(pipeline, "刚才那个")

    assert timing["route"] == "context"
    assert hermes.calls == []
    assert lightweight.calls == [
        "普通问题",
        expected_context_prompt("普通问题", first_reply, "刚才那个"),
    ]


def test_context_continues_hermes_once_with_prefix():
    pipeline, hermes, lightweight, _ = make_pipeline(
        replies=["天气查询结果。", "上下文天气回答。"]
    )
    run_text(pipeline, "帮我查天气")

    timing = run_text(pipeline, "刚才说的")

    assert timing["route"] == "context"
    assert lightweight.calls == []
    assert hermes.calls == [
        "帮我查天气",
        expected_context_prompt("帮我查天气", "天气查询结果。", "刚才说的"),
    ]


def test_context_after_rag_does_not_search_or_rewrap_knowledge_prefix():
    rag = CapturingRAG([
        {"doc": {"title": "知识", "text": "参考内容"}},
    ])
    pipeline, hermes, lightweight, _ = make_pipeline(
        replies=["知识回答。", "知识追问回答。"], rag=rag
    )
    run_text(pipeline, "知识问题")
    assert len(rag.calls) == 1
    assert "【知识库参考" in lightweight.calls[0]

    timing = run_text(pipeline, "那个呢")

    assert timing["route"] == "context"
    assert len(rag.calls) == 1
    assert len(lightweight.calls) == 2
    assert lightweight.calls[1] == expected_context_prompt(
        "知识问题", "知识回答。", "那个呢"
    )
    assert "【知识库参考" not in lightweight.calls[1]
    assert hermes.calls == []


class MutableHealth:
    hr_high = 100
    hr_low = 60
    hr_low_night = 50
    night_start = 23
    night_end = 6

    def __init__(self, hr=72, spo2=98):
        self.hr = hr
        self.spo2 = spo2

    def get_fresh_values(self, stale_seconds):
        return self.hr, self.spo2


def test_context_after_data_reuses_local_health_template_without_llm():
    health = MutableHealth(hr=72, spo2=98)
    pipeline, hermes, lightweight, tts = make_pipeline(health=health)
    run_text(pipeline, "心率多少")
    health.hr = 75

    timing = run_text(pipeline, "那这个呢")

    assert timing["route"] == "context"
    assert "心率 75" in tts.texts[-1]
    assert "血氧 98" in tts.texts[-1]
    assert hermes.calls == []
    assert lightweight.calls == []


def test_context_after_data_without_fresh_values_uses_honest_fallback():
    health = MutableHealth(hr=72, spo2=98)
    pipeline, hermes, lightweight, tts = make_pipeline(health=health)
    run_text(pipeline, "心率多少")
    health.hr = None
    health.spo2 = None

    timing = run_text(pipeline, "刚才那个呢")

    assert timing["route"] == "context"
    assert tts.texts[-1] == "我有点没跟上，你是指哪件事呀？"
    assert hermes.calls == []
    assert lightweight.calls == []


def test_replay_after_stale_data_context_repeats_honest_fallback_not_old_values():
    health = MutableHealth(hr=72, spo2=98)
    pipeline, hermes, lightweight, tts = make_pipeline(health=health)
    run_text(pipeline, "心率多少")
    health.hr = None
    health.spo2 = None

    context_timing = run_text(pipeline, "刚才那个呢")
    fallback_text = tts.texts[-1]
    replay_timing = run_text(pipeline, "重新说一遍")

    assert context_timing["route"] == "context"
    assert fallback_text == "我有点没跟上，你是指哪件事呀？"
    assert replay_timing["route"] == "replay"
    assert replay_timing["llm_backend"] == "replay"
    assert tts.texts[-1] == fallback_text
    assert "72" not in tts.texts[-1]
    assert "98" not in tts.texts[-1]
    assert hermes.calls == []
    assert lightweight.calls == []


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def test_replay_snapshot_expires_after_600_seconds(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(pipeline_module.time, "monotonic", clock)
    pipeline, _, _, tts = make_pipeline(replies=["原回答。"])
    run_text(pipeline, "普通问题")
    clock.advance(601)

    timing = run_text(pipeline, "再说一遍")

    assert timing["llm_backend"] == "template"
    assert tts.texts[-1] == "刚才没有可以重复的内容哦，先跟我说说话吧。"


def test_replay_does_not_refresh_snapshot_ttl(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(pipeline_module.time, "monotonic", clock)
    pipeline, _, _, tts = make_pipeline(replies=["原回答。"])
    run_text(pipeline, "普通问题")
    clock.advance(500)
    first_replay = run_text(pipeline, "重新说一遍")
    assert first_replay["llm_backend"] == "replay"
    assert tts.texts[-1] == "原回答。"

    clock.advance(101)
    second_replay = run_text(pipeline, "再说一次")

    assert second_replay["llm_backend"] == "template"
    assert tts.texts[-1] == "刚才没有可以重复的内容哦，先跟我说说话吧。"


def test_ordinary_success_overwrites_snapshot():
    pipeline, _, _, tts = make_pipeline(replies=["第一轮。", "第二轮。"])
    run_text(pipeline, "问题一")
    run_text(pipeline, "问题二")

    run_text(pipeline, "重复一次")

    assert tts.texts[-1] == "第二轮。"


def test_successful_context_becomes_the_single_next_snapshot():
    pipeline, _, lightweight, tts = make_pipeline(
        replies=["第一轮回答。", "第一次追问回答。", "第二次追问回答。"]
    )
    run_text(pipeline, "问题一")
    run_text(pipeline, "刚才那个")
    run_text(pipeline, "那个呢")

    assert lightweight.calls[-1] == expected_context_prompt(
        "刚才那个", "第一次追问回答。", "那个呢"
    )
    run_text(pipeline, "再说一遍")
    assert tts.texts[-1] == "第二次追问回答。"


class SwitchableTTS(CapturingTTS):
    def __init__(self):
        super().__init__()
        self.fail = False

    async def synthesize(self, text):
        if self.fail:
            raise RuntimeError("injected TTS failure")
        return await super().synthesize(text)


def test_replay_tts_failure_does_not_dirty_snapshot():
    tts = SwitchableTTS()
    pipeline, _, _, _ = make_pipeline(replies=["可重复回答。"], tts=tts)
    run_text(pipeline, "普通问题")
    tts.fail = True

    async def collect_failed_replay():
        return [frame async for frame in pipeline.run_text("再说一遍")]

    assert asyncio.run(collect_failed_replay()) == []
    tts.fail = False
    timing = run_text(pipeline, "重新说一次")

    assert timing["llm_backend"] == "replay"
    assert tts.texts[-1] == "可重复回答。"


def test_ordinary_tts_failure_preserves_previous_snapshot():
    tts = SwitchableTTS()
    pipeline, _, _, _ = make_pipeline(
        replies=["稳定回答。", "不应提交。"], tts=tts
    )
    run_text(pipeline, "稳定问题")
    tts.fail = True

    async def collect_failed_round():
        return [frame async for frame in pipeline.run_text("失败问题")]

    assert asyncio.run(collect_failed_round()) == []
    tts.fail = False
    run_text(pipeline, "重复一遍")

    assert tts.texts[-1] == "稳定回答。"


class PartiallyFailingStreamTTS(CapturingTTS):
    def __init__(self):
        super().__init__()
        self.fail_midstream = False

    async def stream_synthesize(self, text):
        self.texts.append(text)
        yield wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)
        if self.fail_midstream:
            raise TTSError("injected streaming TTS interruption")


def test_streaming_tts_partial_failure_preserves_previous_snapshot():
    tts = PartiallyFailingStreamTTS()
    pipeline, _, _, _ = make_pipeline(
        replies=["稳定回答。", "不应提交的流式回答。"], tts=tts
    )
    run_text(pipeline, "稳定问题")
    tts.fail_midstream = True

    async def collect_partial_failure():
        return [frame async for frame in pipeline.run_text("流式失败问题")]

    # 允许已生成的部分音频发出，但该不完整轮次不得覆盖成功快照。
    assert asyncio.run(collect_partial_failure())
    tts.fail_midstream = False
    run_text(pipeline, "重复一次")

    assert tts.texts[-1] == "稳定回答。"


class InterruptingLLM(CapturingLLM):
    def __init__(self):
        super().__init__(["稳定回答。"])
        self.interrupt = False

    def stream_chat(self, text):
        self.calls.append(text)
        if not self.interrupt:
            return iter(["稳定回答。"])

        def broken_stream():
            yield "未完成的回答。"
            raise RuntimeError("injected LLM interruption")

        return broken_stream()


def test_interrupted_llm_round_preserves_previous_snapshot():
    lightweight = InterruptingLLM()
    pipeline, _, _, tts = make_pipeline(lightweight=lightweight)
    run_text(pipeline, "稳定问题")
    lightweight.interrupt = True

    async def collect_interrupted():
        return [frame async for frame in pipeline.run_text("失败问题")]

    with pytest.raises(RuntimeError, match="injected LLM interruption"):
        asyncio.run(collect_interrupted())
    lightweight.interrupt = False
    run_text(pipeline, "再来一遍")

    assert tts.texts[-1] == "稳定回答。"


class FailingSecondLightweight(CapturingLLM):
    def stream_chat(self, text):
        self.calls.append(text)
        if len(self.calls) == 1:
            return iter(["轻量回答。"])
        raise LLMError("injected lightweight failure")


def test_context_lightweight_fallback_keeps_context_prefix_for_hermes():
    lightweight = FailingSecondLightweight()
    hermes = CapturingLLM(["Hermes 上下文回答。"])
    pipeline, _, _, _ = make_pipeline(
        lightweight=lightweight, hermes=hermes
    )
    run_text(pipeline, "普通问题")

    timing = run_text(pipeline, "刚才那个")

    assert timing["route"] == "context"
    assert hermes.calls == [
        expected_context_prompt("普通问题", "轻量回答。", "刚才那个")
    ]


def test_cancelled_round_preserves_previous_snapshot():
    pipeline, _, _, tts = make_pipeline(replies=["稳定回答。", "不应提交。"])
    run_text(pipeline, "稳定问题")

    async def start_then_cancel():
        stream = pipeline.run_text("取消问题")
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(start_then_cancel())
    run_text(pipeline, "重新播一遍")

    assert tts.texts[-1] == "稳定回答。"


class PairingLLM(CapturingLLM):
    def __init__(self):
        super().__init__()

    def stream_chat(self, text):
        self.calls.append(text)
        if text.startswith("【上一轮】"):
            return iter(["并发后追问。"])
        reply = {"请求A": "回答A。", "请求B": "回答B。"}[text]
        delay = 0.03 if text == "请求A" else 0.01

        def delayed():
            time.sleep(delay)
            yield reply

        return delayed()


def test_concurrent_successes_leave_one_complete_non_torn_snapshot():
    lightweight = PairingLLM()
    pipeline, _, _, _ = make_pipeline(lightweight=lightweight)

    async def collect(text):
        return [frame async for frame in pipeline.run_text(text)]

    async def run_pair():
        return await asyncio.gather(collect("请求A"), collect("请求B"))

    frames_a, frames_b = asyncio.run(run_pair())
    assert frames_a and frames_b
    run_text(pipeline, "刚才说的是什么")

    assert lightweight.calls[-1] in {
        expected_context_prompt("请求A", "回答A。", "刚才说的是什么"),
        expected_context_prompt("请求B", "回答B。", "刚才说的是什么"),
    }
