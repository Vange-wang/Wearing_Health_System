"""Bounded audio request readers and the process-wide voice session gate."""

from __future__ import annotations

import asyncio
import io
import threading
import wave
from collections.abc import AsyncIterable, AsyncIterator


class AudioInputError(ValueError):
    """The uploaded audio is malformed or violates the input contract."""


class AudioInputTooLarge(AudioInputError):
    """The request exceeded the configured byte or duration limit."""


class AudioInputIdleTimeout(AudioInputError):
    """The streaming request stopped producing body chunks."""


class VoiceSessionLock:
    """A non-waiting process-local gate for the single BOX-3 voice session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


async def bounded_chunks(
    chunks: AsyncIterable[bytes], max_bytes: int,
    idle_timeout_seconds: float | None = None,
) -> AsyncIterator[bytes]:
    """Yield request chunks while enforcing the limit before downstream use."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if idle_timeout_seconds is not None and idle_timeout_seconds <= 0:
        raise ValueError("idle_timeout_seconds must be positive")
    total = 0
    iterator = chunks.__aiter__()
    while True:
        try:
            if idle_timeout_seconds is None:
                chunk = await anext(iterator)
            else:
                chunk = await asyncio.wait_for(
                    anext(iterator), timeout=idle_timeout_seconds
                )
        except StopAsyncIteration:
            break
        except TimeoutError as exc:
            raise AudioInputIdleTimeout(
                f"audio stream idle for {idle_timeout_seconds:g}s"
            ) from exc
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise AudioInputTooLarge(
                f"audio_too_long: request exceeds {max_bytes} bytes"
            )
        yield chunk


async def collect_bounded(chunks: AsyncIterable[bytes], max_bytes: int) -> bytes:
    """Collect a bounded async byte stream without an unbounded read call."""
    result = bytearray()
    async for chunk in bounded_chunks(chunks, max_bytes):
        result.extend(chunk)
    return bytes(result)


async def read_upload_bounded(upload, max_bytes: int, chunk_bytes: int = 64 * 1024) -> bytes:
    """Read an UploadFile in fixed chunks with an immediate byte ceiling."""
    async def chunks():
        while True:
            chunk = await upload.read(chunk_bytes)
            if not chunk:
                break
            yield chunk

    return await collect_bounded(chunks(), max_bytes)


def validate_pcm16(data: bytes, sample_rate: int, max_seconds: float) -> None:
    """Validate complete mono PCM16 samples and their configured duration."""
    if len(data) % 2:
        raise AudioInputError("bad_audio_format: raw PCM must contain complete 16-bit samples")
    max_pcm_bytes = int(sample_rate * 2 * max_seconds)
    if len(data) > max_pcm_bytes:
        raise AudioInputTooLarge(
            f"audio_too_long: {len(data) / (sample_rate * 2):.1f}s > {max_seconds:g}s"
        )


def validate_wav(data: bytes, sample_rate: int, max_seconds: float) -> None:
    """Validate WAV metadata and duration without scanning or decoding its PCM body."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            frame_rate = wav.getframerate()
            frame_count = wav.getnframes()
    except (EOFError, wave.Error) as exc:
        raise AudioInputError(f"bad_audio_format: 无法解析 WAV（{exc}）") from exc
    if channels != 1 or sample_width != 2 or frame_rate != sample_rate:
        raise AudioInputError(
            "bad_audio_format: "
            f"channels={channels} sampwidth={sample_width} rate={frame_rate} "
            f"(expect mono/16bit/{sample_rate})"
        )
    duration = frame_count / frame_rate
    if duration > max_seconds:
        raise AudioInputTooLarge(
            f"audio_too_long: {duration:.1f}s > {max_seconds:g}s"
        )
