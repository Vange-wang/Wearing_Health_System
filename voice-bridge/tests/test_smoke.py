"""voice-bridge v0.2 测试（Spec §9.2，10 条 T1~T10）。

mock（T1~T5、T9）+ 单元（T6~T8）+ 真实集成（T10，缺资源自动 skip）。
"""
import io
import json
import math
import struct
import sys
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
ASR_MODEL_DIR = BASE_DIR / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"

sys.path.insert(0, str(BASE_DIR))
from app.main import app  # noqa: E402
from app.pipeline import StreamingPipeline, decode_frame, encode_frame, FrameTooLargeError  # noqa: E402
from app.splitter import SentenceBuffer  # noqa: E402
from app.vad import VADGate  # noqa: E402
from app.tts import TTSEngine, wrap_pcm_as_wav  # noqa: E402


def make_wav(seconds: float = 1.0, rate: int = 16000, loud: bool = False) -> bytes:
    """生成 16kHz/16bit/mono WAV；loud=True 时为满幅正弦（能过 VAD）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(rate * seconds)
        if loud:
            frames = bytearray()
            for i in range(n):
                v = int(20000 * math.sin(2 * math.pi * 440 * i / rate))
                frames += struct.pack("<h", v)
            w.writeframes(bytes(frames))
        else:
            w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------- T1 · health 返回 ok + tts 嵌套对象 + vad 字段（mock） ----------
def test_t1_health_format(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["asr"] in ("ready", "unavailable")
    tts = body["tts"]
    assert isinstance(tts, dict)
    assert tts["configured_primary"] == "edge"
    assert "active_engine" in tts
    assert body["vad"] in ("enabled", "disabled")


# ---------- T2 · 静音 → 400 no_speech（VAD 拦截，mock pipeline） ----------
def test_t2_silence_returns_no_speech(client, monkeypatch):
    from app.asr import ASRBase
    from app.llm import LLMBase
    from app.tts import TTSBase

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):  # 不应被调用
            raise AssertionError("VAD 应拦截，不该走到 ASR")

    class FakeLLM(LLMBase):
        def chat(self, t):
            raise AssertionError("不该走到 LLM")

        def stream_chat(self, t):
            raise AssertionError("不该走到 LLM")

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            raise AssertionError("不该走到 TTS")

    p = StreamingPipeline(
        asr=FakeASR(), llm=FakeLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=True, rms_threshold=0.005, min_speech_frames=10),
    )
    monkeypatch.setattr("app.main.pipeline", p)
    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("silence.wav", make_wav(1.0, loud=False), "audio/wav")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "no_speech"


# ---------- T3 · 坏格式（非 WAV）→ 400 bad_audio_format（mock） ----------
def test_t3_bad_format_returns_400(client):
    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("in.mp3", b"not-a-wav", "audio/mpeg")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_audio_format"


# ---------- T4 · 损坏 WAV → 400 bad_audio_format（C1） ----------
def test_t4_corrupt_wav_returns_400(client, monkeypatch):
    # 损坏 WAV 在 read_wav_16k_mono 阶段即抛 ValueError，无需真实 pipeline
    class _P:
        def run(self, samples, wav_path):
            raise AssertionError("损坏 WAV 应在读文件阶段拦截")

    monkeypatch.setattr("app.main.pipeline", _P())
    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("bad.wav", b"RIFF\x00\x00garbage-not-a-real-wav", "audio/wav")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "bad_audio_format"


# ---------- T5 · edge 故障注入 → 切 piper 不崩 + health 上报 ----------
def test_t5_edge_failure_falls_back_to_piper():
    from app.tts import TTSBase

    class FailingEdge(TTSBase):
        name = "edge"

        async def synthesize(self, text):
            raise RuntimeError("403 Forbidden (simulated)")

    class FakePiper(TTSBase):
        name = "piper"
        called = False

        async def synthesize(self, text):
            self.called = True
            return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    import asyncio

    fallback = FakePiper()
    engine = TTSEngine(FailingEdge(), fallback)
    result = asyncio.run(engine.synthesize("测试"))
    assert fallback.called is True
    assert result[:4] == b"RIFF"
    h = engine.health()
    assert h["configured_primary"] == "edge"
    assert h["active_engine"] == "piper"
    assert h["fallback_reason"] == "edge_403"


# ---------- T6 · 分句器单测（标点/长句/flush/空句） ----------
def test_t6_sentence_buffer():
    sb = SentenceBuffer(max_chars=10)
    assert sb.feed("你好。") == ["你好。"]
    # 连续标点合并 + 纯标点跳过
    assert sb.feed("啊！！？") == ["啊！"]
    assert sb.feed("。，；") == []
    # 长句保护：超过 max_chars 无标点也切
    assert sb.feed("一二三四五六七八九十") == ["一二三四五六七八九十"]
    # flush 剩余无标点内容
    sb.feed("结尾")
    assert sb.flush() == ["结尾"]


# ---------- T7 · VAD 静音拦截单测（rms 阈值边界） ----------
def test_t7_vad_threshold():
    import numpy as np

    v = VADGate(enabled=True, rms_threshold=0.005, min_speech_frames=10)
    silence = np.zeros(16000, dtype=np.float32)          # 1s 静音
    assert v.is_speech(silence) is False
    loud = (np.sin(np.linspace(0, 440 * 2 * math.pi, 16000)) * 0.5).astype(np.float32)
    assert v.is_speech(loud) is True
    # disabled → 放行
    v2 = VADGate(enabled=False, rms_threshold=0.005, min_speech_frames=10)
    assert v2.is_speech(silence) is True


# ---------- T8 · 帧协议单测（编码/解析 + 最大帧长守卫） ----------
def test_t8_frame_protocol():
    payload = b"hello-wav"
    frame = encode_frame(payload, 1024)
    assert frame == struct.pack(">I", len(payload)) + payload
    got, rest = decode_frame(frame + b"tail")
    assert got == payload
    assert rest == b"tail"
    with pytest.raises(FrameTooLargeError):
        encode_frame(b"x" * 100, max_frame_bytes=50)
    with pytest.raises(ValueError):
        decode_frame(b"\x00")


# ---------- T9 · 流式全链路（mock LLM/TTS）→ 帧可解析 + X-Timing ----------
def test_t9_stream_full_chain(client, monkeypatch):
    from app.asr import ASRBase
    from app.llm import LLMBase
    from app.tts import TTSBase

    class FakeASR(ASRBase):
        def transcribe(self, wav_path):
            return "你好，今天天气怎么样。"

    class FakeLLM(LLMBase):
        def chat(self, t):
            return ""

        def stream_chat(self, t):
            return iter(["今天天气", "不错。", "适合出门。"])

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            # 返回可解析的合法 WAV（16k/16bit/mono，20ms）
            return wrap_pcm_as_wav(b"\x00\x00" * 320, 16000)

    p = StreamingPipeline(
        asr=FakeASR(), llm=FakeLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=True, rms_threshold=0.005, min_speech_frames=10),
        sentence_max_chars=50,
    )
    monkeypatch.setattr("app.main.pipeline", p)

    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("speech.wav", make_wav(1.0, loud=True), "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["x-audio-framing"] == "wav-length-prefixed"
    timing = json.loads(resp.headers["x-timing"])
    assert "open_ms" in timing and timing["open_ms"] >= 0

    # 逐帧解析，每帧都是合法 WAV
    body = resp.content
    frames = []
    while body:
        payload, body = decode_frame(body)
        frames.append(payload)
    assert len(frames) >= 2  # 至少两句
    for f in frames:
        assert f[:4] == b"RIFF"


# ---------- T10 · 真实全链路 → open_ms 墙钟 + 帧可播（需模型+key+网络） ----------
def _has_llm_key() -> bool:
    import os

    if os.environ.get("DEEPSEEK_API_KEY"):
        return True
    env_file = BASE_DIR / ".env"
    return env_file.exists() and "DEEPSEEK_API_KEY" in env_file.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not (ASR_MODEL_DIR.exists() and _has_llm_key()),
    reason="需 ASR 模型 + DeepSeek key + 网络",
)
def test_t10_real_full_chain(client):
    resp = client.post(
        "/api/v1/voice/chat/stream",
        files={"audio": ("speech.wav", make_wav(2.0, loud=True), "audio/wav")},
    )
    # 真实集成必须 200，不得接受 400/502 假阳性（Spec C3）
    assert resp.status_code == 200
    timing = json.loads(resp.headers["x-timing"])
    assert timing["open_ms"] >= 0
    body = resp.content
    frames = []
    while body:
        payload, body = decode_frame(body)
        frames.append(payload)
    assert len(frames) >= 1
    assert all(f[:4] == b"RIFF" for f in frames)
