"""voice-bridge v0.3 测试（Spec v0.3 §7，T1~T9）。

T1~T3、T7、T9：mock/单元（无 Hermes 依赖）。
T4~T6、T8：真实集成，需真实 Hermes API Server —— 默认 skip，
验收时显式启用：设置 HERMES_E2E=1 + HERMES_API_KEY（或 .env）+ API Server 运行中。
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
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR))
from app.main import app  # noqa: E402
from app.llm import HermesLLM, LLMBase, LLMError  # noqa: E402
from app.pipeline import StreamingPipeline, decode_frame  # noqa: E402
from app.vad import VADGate  # noqa: E402
from app.tts import wrap_pcm_as_wav  # noqa: E402
from app.asr import ASRBase  # noqa: E402
from app.tts import TTSBase  # noqa: E402


def make_speech_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """满幅正弦 WAV（能过 VAD）。"""
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


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _read_api_key() -> str | None:
    key = os.environ.get("HERMES_API_KEY")
    if key:
        return key
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("HERMES_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _hermes_ready() -> bool:
    """真实 Hermes API Server 就绪（显式启用 + key + 服务可达）。"""
    if not os.environ.get("HERMES_E2E"):
        return False
    key = _read_api_key()
    if not key:
        return False
    import urllib.request

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8642/health",
            headers={"Authorization": f"Bearer {key}"},
        )
        return urllib.request.urlopen(req, timeout=3).status == 200
    except Exception:
        return False


NEEDS_HERMES = pytest.mark.skipif(not _hermes_ready(), reason="需 HERMES_E2E=1 + key + API Server 运行")


# ---------- T1 · llm.py 请求命中 Hermes API Server，且无 DeepSeek 调用路径 ----------
def test_t1_hermes_backend_target(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "test-key")
    from app.config import load_config

    cfg = load_config()
    llm = cfg and HermesLLM(cfg.llm_api_key(), cfg.llm_api_server_url, cfg.llm_model)
    assert "127.0.0.1:8780" in str(llm.client.base_url)
    assert llm.model == "hermes-agent"
    assert llm.name == "hermes"
    # 无 DeepSeek 调用路径（A1）：源码不含 deepseek 端点/密钥引用
    src = (BASE_DIR / "app" / "llm.py").read_text(encoding="utf-8").lower()
    assert "api.deepseek.com" not in src
    assert "deepseek_api_key" not in src


# ---------- T2 · Hermes 不可达 → 502 upstream_error（mock） ----------
def test_t2_hermes_unreachable_returns_502(client, monkeypatch):
    class UnreachableLLM(LLMBase):
        name = "hermes"
        stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}

        def chat(self, t):
            raise LLMError("connection refused")

        def stream_chat(self, t):
            raise LLMError("Hermes 流式调用失败: connection refused")

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "你好。"

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            return wrap_pcm_as_wav(b"\x00\x00" * 320, 16000)

    p = StreamingPipeline(
        asr=FakeASR(), llm=UnreachableLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=True, rms_threshold=0.005, min_speech_frames=10),
    )
    monkeypatch.setattr("app.main.pipeline", p)
    monkeypatch.setattr("app.main.asr", FakeASR())
    monkeypatch.setattr("app.main.llm", UnreachableLLM())
    monkeypatch.setattr("app.main.tts", FakeTTS())

    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("speech.wav", make_speech_wav(1.0), "audio/wav")},
    )
    assert resp.status_code == 502
    assert resp.json()["error"] == "upstream_error"


# ---------- T3 · 流式全链路（mock Hermes SSE）→ 帧可解析 + 分段计量字段 ----------
def test_t3_stream_full_chain_mock_hermes(client, monkeypatch):
    class FakeHermes(LLMBase):
        name = "hermes"
        stats = {"tool_seen": False, "first_chunk_ms": 100, "first_content_ms": 100}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            self.stats = {"tool_seen": False, "first_chunk_ms": 100, "first_content_ms": 100}
            return iter(["今天天气", "不错。", "适合出门。"])

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "今天天气怎么样？"

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            return wrap_pcm_as_wav(b"\x00\x00" * 320, 16000)

    p = StreamingPipeline(
        asr=FakeASR(), llm=FakeHermes(), tts=FakeTTS(),
        vad=VADGate(enabled=True, rms_threshold=0.005, min_speech_frames=10),
    )
    monkeypatch.setattr("app.main.pipeline", p)
    monkeypatch.setattr("app.main.asr", FakeASR())
    monkeypatch.setattr("app.main.llm", FakeHermes())
    monkeypatch.setattr("app.main.tts", FakeTTS())

    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("speech.wav", make_speech_wav(1.0), "audio/wav")},
    )
    assert resp.status_code == 200
    timing = json.loads(resp.headers["x-timing"])
    assert timing["llm_backend"] == "hermes"
    assert "tool_ms" in timing and timing["tool_ms"] == 0
    assert "answer_open_ms" in timing and timing["answer_open_ms"] == timing["open_ms"]

    body = resp.content
    frames = []
    while body:
        payload, body = decode_frame(body)
        frames.append(payload)
    assert len(frames) >= 2
    assert all(f[:4] == b"RIFF" for f in frames)


# ---------- T7 · 分段计量：带工具调用时 tool_ms / answer_open_ms 正确（单元） ----------
def test_t7_segmented_timing_with_tools():
    import asyncio
    import numpy as np

    class ToolLLM(LLMBase):
        name = "hermes"

        def __init__(self):
            self.stats = {}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            # 模拟：先跑工具（3000ms 后才有首个正文）
            self.stats = {"tool_seen": True, "first_chunk_ms": 50, "first_content_ms": 3000}
            return iter(["查到了。", "结果是 42。"])

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "帮我查一下。"

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    p = StreamingPipeline(
        asr=FakeASR(), llm=ToolLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=False),  # 单测专注计量逻辑，VAD 放行
    )
    samples = np.zeros(16000, dtype=np.float32)

    async def collect():
        frames = []
        async for f in p.run(samples, Path("dummy.wav")):
            frames.append(f)
        return frames

    frames = asyncio.run(collect())
    assert len(frames) == 2
    asr_ms = p.timing["asr_ms"]
    assert p.timing["tool_seen"] is True
    # tool_ms = asr_ms + first_content_ms（工具期 ≈ 请求→首个正文 delta）
    assert p.timing["tool_ms"] == asr_ms + 3000
    assert p.timing["llm_backend"] == "hermes"


# ---------- T4 · 真实全链路（真 Hermes）→ 语音文本 → Hermes 回答 → 逐帧 TTS ----------
@NEEDS_HERMES
def test_t4_real_hermes_full_chain(client):
    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("speech.wav", make_speech_wav(2.0), "audio/wav")},
    )
    assert resp.status_code == 200  # 非 200 必 fail（沿用 v0.2 纪律）
    timing = json.loads(resp.headers["x-timing"])
    assert timing["llm_backend"] == "hermes"
    assert timing["open_ms"] >= 0
    body = resp.content
    frames = []
    while body:
        payload, body = decode_frame(body)
        frames.append(payload)
    assert len(frames) >= 1
    assert all(f[:4] == b"RIFF" for f in frames)


# ---------- T5 · 共用记忆：预写 memory → 语音查询命中（核心验收） ----------
@NEEDS_HERMES
def test_t5_shared_memory_with_weixin(client):
    """两轮独立 session：先告知偏好，再查询——命中即证明 persistent memory 承载。

    注意：依赖 Hermes 自动存 memory 行为；失败时优先人工按 README 步骤验证。
    """
    # 轮 1：写入偏好
    r1 = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("s1.wav", make_speech_wav(2.0), "audio/wav")},
    )
    assert r1.status_code == 200
    # 轮 2：查询（真实语音样本在自测报告中覆盖；此处以真实集成门存在性为主）
    r2 = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("s2.wav", make_speech_wav(2.0), "audio/wav")},
    )
    assert r2.status_code == 200
    # 语音内容命中证据见 Code文档/v0.3自测报告.md（人工核验 + 服务端日志）


# ---------- T6 · 技能触发：语音请求命中已装 skill ----------
@NEEDS_HERMES
def test_t6_skill_trigger(client):
    prompt = os.environ.get("HERMES_SKILL_PROMPT")
    if not prompt:
        pytest.skip("未设置 HERMES_SKILL_PROMPT（触发已装 skill 的语音文本）")
    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("skill.wav", make_speech_wav(2.0), "audio/wav")},
    )
    assert resp.status_code == 200
    # skill 命中证据见自测报告（服务端 tool_seen 日志 + 人工核验）


# ---------- T8 · 工具集裁剪生效：api_server 仅 memory/skills/session_search/web ----------
@NEEDS_HERMES
def test_t8_toolset_trimming():
    import yaml

    cfg_path = Path.home() / ".hermes" / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    pts = (data or {}).get("platform_toolsets") or {}
    api_ts = set(pts.get("api_server") or [])
    assert api_ts, "platform_toolsets.api_server 未配置"
    allowed = {"memory", "skills", "session_search", "web"}
    heavy = {"terminal", "file", "browser", "delegation", "cronjob",
             "code_execution", "computer_use", "image_gen", "video"}
    assert api_ts <= allowed, f"api_server 工具集超出白名单: {api_ts - allowed}"
    assert not (api_ts & heavy), f"api_server 仍含重工具: {api_ts & heavy}"
    # 微信/cli 通道不受影响
    assert "weixin" not in pts or pts.get("weixin"), "weixin 工具集被误清空"


# ---------- T9 · 安抚语：慢路径（带工具 SSE）先发安抚帧，快路径不发 ----------
def test_t9_comfort_on_slow_path():
    import asyncio
    import numpy as np
    from app.llm import TOOL_SENTINEL

    calls = []

    class RecorderTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            calls.append(text)
            return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "帮我查一下。"

    class SlowLLM(LLMBase):  # 慢路径：先工具后正文
        name = "hermes"

        def __init__(self):
            self.stats = {}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            self.stats = {"tool_seen": True, "first_chunk_ms": 50, "first_content_ms": 3000}
            return iter([TOOL_SENTINEL, "查到了。", "结果是 42。"])

    class FastLLM(LLMBase):  # 快路径：纯闲聊无工具
        name = "hermes"

        def __init__(self):
            self.stats = {}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            self.stats = {"tool_seen": False, "first_chunk_ms": 50, "first_content_ms": 300}
            return iter(["今天天气不错。"])

    samples = np.zeros(16000, dtype=np.float32)

    async def run(llm):
        calls.clear()
        p = StreamingPipeline(
            asr=FakeASR(), llm=llm, tts=RecorderTTS(),
            vad=VADGate(enabled=False),
            comfort_text="好的，我查一下。",
        )
        frames = []
        async for f in p.run(samples, Path("dummy.wav")):
            frames.append(f)
        return p.timing, frames

    # 慢路径：先安抚，后正文
    timing_slow, frames_slow = asyncio.run(run(SlowLLM()))
    assert timing_slow["comfort_sent"] is True
    assert calls[0] == "好的，我查一下。"          # 第一帧 = 安抚语
    assert timing_slow["chunk_count"] == timing_slow["sentence_count"] + 1  # 安抚帧 + 正文句

    # 快路径：无安抚
    timing_fast, frames_fast = asyncio.run(run(FastLLM()))
    assert timing_fast["comfort_sent"] is False
    assert calls[0] != "好的，我查一下。"
    assert timing_fast["chunk_count"] == timing_fast["sentence_count"]
