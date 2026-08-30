import asyncio

import pytest
from fastapi.testclient import TestClient

from app.audio_input import (
    AudioInputError,
    AudioInputIdleTimeout,
    AudioInputTooLarge,
    VoiceSessionLock,
    bounded_chunks,
    collect_bounded,
    validate_pcm16,
)


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


def test_upload_over_configured_bytes_is_rejected_while_reading():
    async def run():
        with pytest.raises(AudioInputTooLarge):
            await collect_bounded(_chunks(b"1234", b"56"), max_bytes=5)

    asyncio.run(run())


def test_stalled_request_body_hits_idle_timeout():
    async def stalled_chunks():
        yield b"\x00\x00"
        await asyncio.Event().wait()

    async def run():
        received = []
        with pytest.raises(AudioInputIdleTimeout):
            async for chunk in bounded_chunks(
                stalled_chunks(), max_bytes=100, idle_timeout_seconds=0.01
            ):
                received.append(chunk)
        assert received == [b"\x00\x00"]

    asyncio.run(run())


def test_odd_raw_pcm_tail_is_rejected():
    with pytest.raises(AudioInputError, match="16-bit"):
        validate_pcm16(b"\x00\x01\x02", sample_rate=16_000, max_seconds=15)


def test_second_concurrent_voice_session_is_rejected_without_waiting():
    lock = VoiceSessionLock()
    assert lock.try_acquire() is True
    assert lock.try_acquire() is False
    lock.release()
    assert lock.try_acquire() is True
    lock.release()


def _auth_headers(main):
    return {"X-Device-Token": main.app.state.device_auth.token}


def test_oversized_wav_upload_returns_413(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "asr", object())
    monkeypatch.setattr(main, "llm", object())
    monkeypatch.setattr(main, "tts", object())
    monkeypatch.setattr(main.cfg, "pipeline_max_input_bytes", 5)
    response = TestClient(main.app).post(
        "/api/v1/voice/chat",
        files={"audio": ("sample.wav", b"123456", "audio/wav")},
        headers=_auth_headers(main),
    )
    assert response.status_code == 413
    assert response.json()["error"] == "audio_too_long"
    assert not main.voice_session_lock.locked()


class _StreamingASRStub:
    def create_stream(self):
        return object()

    def accept(self, stream, samples):
        pass

    def partial(self, stream):
        return ""

    def final(self, stream):
        raise AssertionError("invalid PCM must be rejected before final decode")


def test_odd_raw_pcm_endpoint_returns_400(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "streaming_asr", _StreamingASRStub())
    monkeypatch.setattr(main, "pipeline", object())
    monkeypatch.setattr(main.cfg, "pipeline_max_input_bytes", 100)
    response = TestClient(main.app).post(
        "/api/v1/voice/stream",
        content=b"\x00\x01\x02",
        headers=_auth_headers(main),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "bad_audio_format"
    assert not main.voice_session_lock.locked()


def test_busy_voice_endpoint_returns_409(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "streaming_asr", _StreamingASRStub())
    monkeypatch.setattr(main, "pipeline", object())
    assert main.voice_session_lock.try_acquire()
    try:
        response = TestClient(main.app).post(
            "/api/v1/voice/stream",
            content=b"\x00\x00",
            headers=_auth_headers(main),
        )
        assert response.status_code == 409
        assert response.json()["error"] == "device_busy"
    finally:
        main.voice_session_lock.release()


def test_stalled_raw_stream_returns_408_and_releases_session(monkeypatch):
    from app import main

    async def stalled(*args, **kwargs):
        raise AudioInputIdleTimeout("audio stream idle timeout")
        yield b""  # pragma: no cover - keep this an async generator

    monkeypatch.setattr(main, "streaming_asr", _StreamingASRStub())
    monkeypatch.setattr(main, "pipeline", object())
    monkeypatch.setattr(main, "bounded_chunks", stalled)
    response = TestClient(main.app).post(
        "/api/v1/voice/stream",
        content=b"\x00\x00",
        headers=_auth_headers(main),
    )
    assert response.status_code == 408
    assert response.json()["error"] == "audio_timeout"
    assert not main.voice_session_lock.locked()
