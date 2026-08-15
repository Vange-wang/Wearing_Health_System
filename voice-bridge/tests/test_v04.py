"""voice-bridge v0.4 测试（Spec §7，T1~T8）。

T1/T3：单元（流式 ASR / run_text）。
T2/T5/T6/T7：真实集成（需流式模型 + DeepSeek / 硬件），默认按资源 skip。
"""
import io
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR))
from app.asr import StreamingASR  # noqa: E402
from app.pipeline import StreamingPipeline, decode_frame  # noqa: E402
from app.vad import VADGate  # noqa: E402
from app.asr import ASRBase  # noqa: E402
from app.tts import TTSBase, wrap_pcm_as_wav  # noqa: E402
from app.llm import LLMBase  # noqa: E402
from app.router import Router  # noqa: E402

STREAM_MODEL = BASE_DIR / "models" / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
TEST_WAV = STREAM_MODEL / "test_wavs" / "0.wav"


def wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


# ---------- T1 · 流式 ASR：喂 PCM → partial 更新 → final ----------
def test_t1_streaming_asr():
    if not STREAM_MODEL.exists():
        pytest.skip("流式模型未下载")
    import numpy as np

    asr = StreamingASR(STREAM_MODEL, 16000)
    pcm = wav_pcm(TEST_WAV)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    stream = asr.create_stream()
    chunk = 16000 * 2  # 2s 一块，模拟流式
    partials = []
    for i in range(0, len(samples), chunk):
        asr.accept(stream, samples[i:i + chunk])
        p = asr.partial(stream)
        if p:
            partials.append(p)
    final = asr.final(stream)
    assert final, "final 结果非空"
    assert len(partials) >= 1, "应有 partial 更新"


# ---------- T3 · pipeline.run_text：文本直进下游（路由/LLM/TTS/帧） ----------
def test_t3_run_text():
    import asyncio
    import numpy as np

    class FakeLLM(LLMBase):
        name = "deepseek"

        def __init__(self):
            self.stats = {"tool_seen": False, "first_chunk_ms": 1, "first_content_ms": 1}

        def chat(self, t):
            return ""

        def stream_chat(self, t):
            return iter(["好的。", "收到。"])

    class FakeTTS(TTSBase):
        name = "piper"

        async def synthesize(self, text):
            return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    p = StreamingPipeline(
        asr=FakeASR_placeholder(), llm=FakeLLM(), tts=FakeTTS(),
        vad=VADGate(enabled=False),
        lightweight_llm=FakeLLM(),
        router=Router(tool_keywords=[], skill_keywords=[]),
        rag=None,
    )

    async def run():
        frames = []
        async for f in p.run_text("你好"):
            frames.append(f)
        return frames

    frames = asyncio.run(run())
    assert p.timing["route"] == "lightweight"
    assert len(frames) >= 1


class FakeASR_placeholder(ASRBase):
    def transcribe(self, wav_path):
        return ""


# ---------- T2 · /voice/stream 真实链路（PCM → 流式 ASR → 帧） ----------
def _has_resources() -> bool:
    if not STREAM_MODEL.exists():
        return False
    env_file = BASE_DIR / ".env"
    return env_file.exists() and "DEEPSEEK_API_KEY" in env_file.read_text(encoding="utf-8")


@pytest.mark.skipif(not _has_resources(), reason="需流式模型 + DeepSeek key")
def test_t2_voice_stream_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app

    pcm = wav_pcm(TEST_WAV)
    with TestClient(app) as c:
        r = c.post("/api/v1/voice/stream", content=pcm,
                   headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    body = r.content
    frames = []
    while body:
        payload, body = decode_frame(body)
        frames.append(payload)
    assert len(frames) >= 1
    assert all(f[:4] == b"RIFF" for f in frames)


# T5/T6/T7 真机联调（需 BOX-3 硬件 + 局域网），留真机阶段执行
