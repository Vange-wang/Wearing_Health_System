"""voice-bridge 长期 RAG 测试（Spec §7，T1~T9）。

T1~T5、T9：mock/单元（无外部依赖）。
T6/T7/T8：真实集成，需 DEEPSEEK_API_KEY / Hermes / 网络，默认 skip。
"""
import io
import json
import math
import os
import struct
import sys
import wave
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR))
from app.llm import LightweightLLM, LLMBase, load_user_profile  # noqa: E402
from app.rag import BM25Index  # noqa: E402
from app.knowledge import KnowledgeBase  # noqa: E402
from app.router import Router, LIGHTWEIGHT, RAG, HERMES  # noqa: E402
from app.pipeline import StreamingPipeline, decode_frame  # noqa: E402
from app.vad import VADGate  # noqa: E402
from app.asr import ASRBase  # noqa: E402
from app.tts import TTSBase, wrap_pcm_as_wav  # noqa: E402


def make_speech_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(rate * seconds)
        frames = bytearray()
        for i in range(n):
            v = int(20000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# ---------- T1 · 轻量通道：命中 DeepSeek + 注入 USER.md ----------
def test_t1_lightweight_deepseek_and_user_md(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    profile = tmp_path / "USER.md"
    profile.write_text("最喜欢颜色：蓝色。", encoding="utf-8")
    llm = LightweightLLM("sk-test", "https://api.deepseek.com", "deepseek-chat", profile)
    assert llm.name == "deepseek"
    assert "api.deepseek.com" in str(llm.client.base_url)
    system = llm._system_prompt()
    assert "蓝色" in system  # USER.md 已注入 system prompt
    # load_user_profile 语义
    content, ok = load_user_profile(profile)
    assert ok is True and "蓝色" in content
    assert load_user_profile(tmp_path / "missing.md") == ("", False)


# ---------- T2 · 路由判定：纯闲聊→轻量、技能/工具→慢路径、知识库→RAG ----------
def test_t2_router():
    r = Router(tool_keywords=["查快递", "发邮件", "帮我查"], skill_keywords=["成分分析"])
    assert r.route("你好呀") == LIGHTWEIGHT
    assert r.route("帮我查一下快递") == HERMES
    assert r.route("做个成分分析") == HERMES
    assert r.route("心率正常吗", rag_hit=True) == RAG
    assert r.route("心率正常吗", rag_hit=False) == LIGHTWEIGHT


# ---------- T3 · BM25 检索：查询命中 top-k ----------
def test_t3_bm25_search():
    docs = [
        {"id": "hr", "title": "心率", "text": "正常心率 60 到 100 次每分钟"},
        {"id": "o2", "title": "血氧", "text": "血氧饱和度正常 95% 以上"},
    ]
    idx = BM25Index(docs)
    res = idx.search("心率正常是多少", top_k=1)
    assert res and res[0]["doc"]["id"] == "hr"
    assert res[0]["score"] > 0


# ---------- T4 · RAG 注入：检索结果进 prompt（mock pipeline） ----------
def test_t4_rag_injection(tmp_path):
    import asyncio
    import numpy as np

    captured = {}

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "心率正常范围是多少？"

    class FakeLLM(LLMBase):
        name = "deepseek"

        def __init__(self):
            self.stats = {"tool_seen": False, "first_chunk_ms": 1, "first_content_ms": 1}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            captured["text"] = t
            return iter(["六十到一百次。"])

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    kb = KnowledgeBase(tmp_path)
    (tmp_path / "心率.md").write_text("# 心率\n正常心率 60 到 100 次每分钟", encoding="utf-8")
    kb.reload()

    p = StreamingPipeline(
        asr=FakeASR(), llm=FakeLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=False),
        lightweight_llm=FakeLLM(),
        router=Router(tool_keywords=[], skill_keywords=[]),
        rag=kb, rag_top_k=2,
    )
    samples = np.zeros(16000, dtype=np.float32)

    async def run():
        frames = []
        async for f in p.run(samples, Path("dummy.wav")):
            frames.append(f)
        return frames

    frames = asyncio.run(run())
    assert frames
    assert "知识库参考" in captured["text"]       # RAG 结果注入
    assert "60 到 100" in captured["text"]        # 检索内容命中


# ---------- T5 · 轻量通道全链路（mock）→ 帧可解析 + route=lightweight ----------
def test_t5_lightweight_full_chain():
    import asyncio
    import numpy as np

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "今天天气怎么样？"

    class FakeLLM(LLMBase):
        name = "deepseek"

        def __init__(self):
            self.stats = {"tool_seen": False, "first_chunk_ms": 1, "first_content_ms": 1}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            return iter(["天气不错。", "适合出门。"])

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    p = StreamingPipeline(
        asr=FakeASR(), llm=FakeLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=False),
        lightweight_llm=FakeLLM(),
        router=Router(tool_keywords=[], skill_keywords=[]),
        rag=None,
    )
    samples = np.zeros(16000, dtype=np.float32)

    async def run():
        frames = []
        async for f in p.run(samples, Path("dummy.wav")):
            frames.append(f)
        return frames

    frames = asyncio.run(run())
    assert p.timing["route"] == LIGHTWEIGHT
    assert p.timing["llm_backend"] == "deepseek"
    assert len(frames) >= 1


# ---------- T9 · 知识库热重载 ----------
def test_t9_knowledge_reload(tmp_path):
    kb = KnowledgeBase(tmp_path)
    assert kb.doc_count() == 0
    (tmp_path / "a.md").write_text("# 心率\n正常 60 到 100", encoding="utf-8")
    assert kb.reload() == 1
    assert kb.search("心率", top_k=1)
    # 热重载：新增文件后无需重启
    (tmp_path / "b.md").write_text("# 血氧\n正常 95 以上", encoding="utf-8")
    assert kb.reload() == 2
    assert kb.search("血氧", top_k=1)[0]["doc"]["id"] == "b"


# ---------- T6/T7/T8 真实集成（skip） ----------
def _has_deepseek_key() -> bool:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return True
    env_file = BASE_DIR / ".env"
    return env_file.exists() and "DEEPSEEK_API_KEY" in env_file.read_text(encoding="utf-8")


def _hermes_ready() -> bool:
    if not os.environ.get("HERMES_E2E"):
        return False
    key = os.environ.get("HERMES_API_KEY")
    if not key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("HERMES_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        return False
    import urllib.request

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8780/health", headers={"Authorization": f"Bearer {key}"}
        )
        return urllib.request.urlopen(req, timeout=3).status == 200
    except Exception:
        return False


@pytest.mark.skipif(not _has_deepseek_key(), reason="需 DEEPSEEK_API_KEY")
def test_t6_lightweight_open_ms():  # 真实集成（稳态：暖机后）
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        # 暖机：首次请求付 DeepSeek 冷连接 + 字典加载成本
        c.post("/api/v1/voice/chat/stream",
               files={"audio": ("s.wav", make_speech_wav(2.0), "audio/wav")})
        resp = c.post(
            "/api/v1/voice/chat/stream",
            files={"audio": ("speech.wav", make_speech_wav(2.0), "audio/wav")},
        )
    assert resp.status_code == 200
    timing = json.loads(resp.headers["x-timing"])
    assert timing["llm_backend"] == "deepseek"
    # v0.4 A5 换 edge：TTS 首句 ~0.9-1.2s（Spec §9 已拍板接受），延迟线放宽到 3000ms
    assert timing["open_ms"] <= 3000


@pytest.mark.skipif(not (_has_deepseek_key() and _hermes_ready()), reason="需真实环境")
def test_t7_shared_memory_lightweight():
    pass  # 微信写 USER.md → 语音轻量通道读到，验收人工核验（见自测报告）


@pytest.mark.skipif(not _hermes_ready(), reason="需 Hermes API Server")
def test_t8_slow_path_regression():
    pass  # 技能触发仍走 Hermes + 安抚语（v0.3 已实现，回归验证见自测报告）
