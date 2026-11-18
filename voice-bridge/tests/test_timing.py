import json
import pytest
from fastapi.testclient import TestClient
from app import main
from app.device_auth import install_device_auth
from app.pipeline import encode_frame
from app.tts import wrap_pcm_as_wav


@pytest.mark.parametrize("backend,route", [("deepseek", "lightweight"), ("template", "data"), ("replay", "replay")])
def test_stream_header_uses_current_request_not_old_hermes_stats(monkeypatch, backend, route):
    class ASR:
        def create_stream(self): return object()
        def accept(self, *args): pass
        def partial(self, *args): return ""
        def final(self, *args): return "当前问题"
    class Pipeline:
        async def run_text(self, text, timing):
            timing["llm_backend"] = backend
            timing["route"] = route
            timing["tool_seen"] = False
            timing["tool_ms"] = 0
            yield encode_frame(wrap_pcm_as_wav(bytes(320), 16000), 4096)
    monkeypatch.setattr(main, "streaming_asr", ASR())
    monkeypatch.setattr(main, "pipeline", Pipeline())
    monkeypatch.setattr(main, "llm", type("OldHermes", (), {
        "stats": {"tool_seen": True, "first_content_ms": 99999}})())
    monkeypatch.setattr(main, "_ms", lambda _: 10)
    monkeypatch.setattr(main.app.state, "device_auth", main.app.state.device_auth)
    install_device_auth(main.app, token="fixture-only", mode="required")
    response = TestClient(main.app).post("/api/v1/voice/stream", content=bytes(320),
                                       headers={"X-Device-Token": "fixture-only"})
    assert response.status_code == 200
    timing = json.loads(response.headers["x-timing"])
    assert timing["llm_backend"] == backend
    assert timing["tool_ms"] == 0
    assert timing["answer_open_ms"] == 10
