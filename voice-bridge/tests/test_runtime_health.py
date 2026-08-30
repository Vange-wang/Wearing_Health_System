import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.llm import HermesLLM, LLMBase, LLMError
from app.pipeline import StreamingPipeline
from app.tts import TTSBase, wrap_pcm_as_wav
from app.vad import VADGate


class _HealthyTTS:
    def __init__(self, probe_ok=True):
        self.probe_ok = probe_ok

    def health(self):
        return {
            "configured_primary": "edge",
            "active_engine": "edge",
            "fallback_reason": None,
            "last_probe_ok": self.probe_ok,
            "last_probe_ts": 1.0,
        }


def test_runtime_health_is_degraded_when_required_component_is_missing(monkeypatch):
    monkeypatch.setattr(main, "asr", object())
    monkeypatch.setattr(main, "streaming_asr", None)
    monkeypatch.setattr(main, "llm", object())
    monkeypatch.setattr(main, "tts", _HealthyTTS())
    monkeypatch.setattr(main, "pipeline", object())

    body = TestClient(main.app).get("/api/v1/health").json()

    assert body["status"] == "degraded"
    assert body["asr"] == "unavailable"


def test_runtime_health_is_ok_only_when_all_required_components_are_ready(monkeypatch):
    monkeypatch.setattr(main, "asr", object())
    monkeypatch.setattr(main, "streaming_asr", object())
    monkeypatch.setattr(main, "llm", object())
    monkeypatch.setattr(main, "tts", _HealthyTTS(probe_ok=True))
    monkeypatch.setattr(main, "pipeline", object())

    body = TestClient(main.app).get("/api/v1/health").json()

    assert body["status"] == "ok"


def test_hermes_stream_http_500_raises_upstream_error(monkeypatch):
    request = httpx.Request("POST", "http://127.0.0.1:8780/v1/chat/completions")

    class ErrorResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("500", request=request, response=httpx.Response(500))

        def iter_lines(self):
            return iter(())

        def close(self):
            pass

    monkeypatch.setattr(httpx.Client, "send", lambda *args, **kwargs: ErrorResponse())
    llm = HermesLLM("test-key", "http://127.0.0.1:8780/v1", "hermes-agent")
    try:
        with pytest.raises(LLMError, match="Hermes 流式调用失败"):
            list(llm.stream_chat("测试"))
    finally:
        if hasattr(llm, "close"):
            llm.close()


def test_reused_hermes_clients_close_together():
    closed = []

    class Client:
        def close(self):
            closed.append(True)

    llm = object.__new__(HermesLLM)
    llm.client = Client()
    llm._stream_client = Client()
    llm.close()
    assert len(closed) == 2


def test_app_shutdown_closes_both_llm_backends(monkeypatch):
    closed = []

    class Backend:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(main, "llm", Backend())
    monkeypatch.setattr(main, "lightweight_llm", Backend())

    asyncio.run(main.shutdown())

    assert len(closed) == 2


def test_unexpected_tts_worker_exception_does_not_hang():
    class FakeLLM(LLMBase):
        name = "fake"
        stats = {}

        def chat(self, text):
            return ""

        def stream_chat(self, text):
            return iter(["一句话。"])

    class ExplodingTTS(TTSBase):
        name = "edge"

        async def synthesize(self, text):
            raise RuntimeError("unexpected")

        async def stream_synthesize(self, text, min_segment_samples=800):
            if False:
                yield b""
            raise RuntimeError("unexpected")

    pipeline = StreamingPipeline(
        asr=None,
        llm=FakeLLM(),
        tts=ExplodingTTS(),
        vad=VADGate(enabled=False),
        sentence_gap_ms=0,
        tts_workers=2,
    )

    async def consume():
        return [frame async for frame in pipeline.run_text("问题")]

    assert asyncio.run(asyncio.wait_for(consume(), timeout=1.0)) == []
