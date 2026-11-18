"""Actual Edge adapter contracts with no real WSS, decoding or model calls."""
import array
import asyncio
from email.utils import formatdate
from types import SimpleNamespace

import aiohttp
import miniaudio
import pytest
from app.pipeline import StreamingPipeline
from app.tts import EdgeTTS, TTSError
from app.vad import VADGate


def fixture_wss(monkeypatch, *, first_403=False, fail_after_audio=False):
    observations = []
    real_request = aiohttp.ClientSession._request
    class WebSocket:
        async def send_str(self, text): pass
        def __aiter__(self):
            async def messages():
                header = b"X-RequestId:fixture\r\nPath:audio\r\nContent-Type:audio/mpeg\r\n"
                for _ in range(2):
                    yield SimpleNamespace(type=aiohttp.WSMsgType.BINARY,
                        data=len(header).to_bytes(2, "big") + header + b"mp3")
                if fail_after_audio: raise RuntimeError("fixture partial disconnect")
                yield SimpleNamespace(type=aiohttp.WSMsgType.TEXT,
                                      data="Path:turn.end\r\n\r\n")
            return messages()
    class Context:
        def __init__(self, session): self.session = session
        async def __aenter__(self):
            observations.append({"session_closed": self.session.closed,
                                 "connector": self.session.connector})
            if first_403 and len(observations) == 1:
                raise aiohttp.ClientResponseError(None, (), status=403,
                                                  headers={"Date": formatdate(usegmt=True)})
            if self.session.closed:
                return await real_request(self.session, "GET", "http://invalid.fixture")
            return WebSocket()
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect",
                        lambda session, *a, **k: Context(session))
    monkeypatch.setattr(miniaudio, "decode", lambda data, **kwargs:
        SimpleNamespace(samples=array.array("h", [1] * (len(data) // 3 * 1000))))
    return observations


def test_actual_edge_internal_403_retry_uses_open_ipv4_connector(monkeypatch):
    observed = fixture_wss(monkeypatch, first_403=True)
    async def exercise():
        segments = [s async for s in EdgeTTS().stream_synthesize("测试")]
        assert segments
        assert len(observed) == 2
        assert not observed[1]["session_closed"]
        assert all(x["connector"].closed for x in observed)
    asyncio.run(exercise())


def test_actual_edge_partial_failure_propagates_without_replay(monkeypatch):
    observed = fixture_wss(monkeypatch, fail_after_audio=True)
    async def exercise():
        segments = []
        with pytest.raises(TTSError):
            async for segment in EdgeTTS().stream_synthesize("测试"):
                segments.append(segment)
        assert segments and len(observed) == 1
    asyncio.run(exercise())


def test_actual_edge_partial_failure_does_not_replace_success_snapshot(monkeypatch):
    fixture_wss(monkeypatch, fail_after_audio=True)
    class LLM:
        name = "fake"
        stats = {}
        def stream_chat(self, text): return iter(["完整回答。"])
    pipeline = StreamingPipeline(None, LLM(), EdgeTTS(), VADGate(enabled=False),
                                 tts_workers=1, sentence_gap_ms=0)
    pipeline._commit_last_round("旧问题", "已完整听到的旧回答。", "hermes")
    before = pipeline._read_last_round()
    async def exercise():
        frames = [frame async for frame in pipeline.run_text("新问题")]
        assert frames, "keep already produced audio; do not replay or discard it"
        assert pipeline._read_last_round() == before
    asyncio.run(exercise())
