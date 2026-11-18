"""Fixed wheel contracts: no real DNS, network, credentials or service writes."""
import asyncio
import hashlib
import io
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import patch
import wave

import aiohttp
import pytest
from edge_tts.constants import SEC_MS_GEC_VERSION
from edge_tts.drm import DRM, generate_sec_ms_gec_v2
from app.edge_connection import owned_communicate
from app.stream_resources import RequestResources
from app.tts import EdgeTTS, TTSError, _EdgePreconnect


def test_paired_v2_binding_and_fixed_vector():
    assert SEC_MS_GEC_VERSION == "2-143.0.3650.75"
    value = generate_sec_ms_gec_v2(1800000000)
    assert len(value) == 81 and value[16] == "-"
    assert generate_sec_ms_gec_v2(1800000299) == value
    assert generate_sec_ms_gec_v2(1800000300) != value
    assert hashlib.sha256(value.encode()).hexdigest() == "2c166724718379e1701fb3f8eb9e43dadf14d76296f685c796f60015862723d6"


def test_actual_communicate_session_never_reads_proxy_or_netrc(monkeypatch):
    import edge_tts
    from test_tts_contract import fixture_wss
    observed = fixture_wss(monkeypatch, first_403=True)
    init = aiohttp.ClientSession.__init__
    settings = []
    def inspect(self, *args, **kwargs):
        settings.append(kwargs.get("trust_env"))
        return init(self, *args, **kwargs)
    monkeypatch.setattr(aiohttp.ClientSession, "__init__", inspect)
    async def exercise():
        assert [part async for part in EdgeTTS().stream_synthesize("测试")]
        assert settings == [False, False]
        assert len(observed) == 2 and all(row["connector"].closed for row in observed)
    asyncio.run(exercise())


def test_cancel_ordinary_stream_releases_connector(monkeypatch):
    import edge_tts
    release = []
    original_stream = edge_tts.Communicate.stream
    async def blocked(self):
        release.append(self.connector)
        await asyncio.Future()
        yield {}
    monkeypatch.setattr(edge_tts.Communicate, "stream", blocked)
    async def exercise():
        generator = EdgeTTS().stream_synthesize("测试")
        task = asyncio.create_task(generator.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        await generator.aclose()
        assert len(release) == 1 and release[0].closed
    asyncio.run(exercise())


@pytest.mark.parametrize("cancel", [False, True])
def test_preconnect_failure_or_cancel_closes_session(monkeypatch, cancel, caplog):
    sessions = []
    original_init = aiohttp.ClientSession.__init__
    def init(self, *args, **kwargs):
        assert kwargs["trust_env"] is False
        original_init(self, *args, **kwargs)
        sessions.append(self)
    async def connect(self, *args, **kwargs):
        if cancel: await asyncio.Future()
        raise RuntimeError("SYNTHETIC_URL_CANARY?Sec-MS-GEC=NEVER_LOG_THIS")
    monkeypatch.setattr(aiohttp.ClientSession, "__init__", init)
    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", connect)
    async def exercise():
        task = asyncio.create_task(EdgeTTS().open_preconnect())
        if cancel:
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        else:
            assert await task is None
        assert sessions and all(item.closed for item in sessions)
    asyncio.run(exercise())
    assert "SYNTHETIC_URL_CANARY" not in caplog.text and "NEVER_LOG_THIS" not in caplog.text


def test_stream_failure_has_no_signed_url_in_public_error(monkeypatch):
    import edge_tts
    async def fail(self):
        raise RuntimeError("SYNTHETIC_URL_CANARY?Sec-MS-GEC=NEVER_LOG_THIS")
        yield {}
    monkeypatch.setattr(edge_tts.Communicate, "stream", fail)
    async def exercise():
        with pytest.raises(TTSError) as caught:
            async for _ in EdgeTTS().stream_synthesize("测试"): pass
        assert str(caught.value).endswith("RuntimeError")
        assert caught.value.__suppress_context__
        assert "CANARY" not in str(caught.value)
    asyncio.run(exercise())


def test_request_lease_closes_preconnect_exactly_once():
    closed = []
    class Resource:
        async def close(self): closed.append(id(self))
    async def exercise():
        resources = RequestResources()
        value = Resource()
        async def result(): return value
        await resources.task(result(), resource_result=True)
        await asyncio.sleep(0)
        await resources.aclose()
        await resources.aclose()
        assert closed == [id(value)]
    asyncio.run(exercise())


def test_preconnect_close_cancellation_retains_owned_cleanup():
    class Resource:
        def __init__(self): self.calls = 0
        async def close(self):
            self.calls += 1
            await asyncio.sleep(0)
    async def exercise():
        session, ws = Resource(), Resource()
        handle = _EdgePreconnect(session, ws, None)
        task = asyncio.create_task(handle.close())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        await handle.close()
        await handle.close()
        assert handle.quiescent and session.calls == ws.calls == 1
    asyncio.run(exercise())
