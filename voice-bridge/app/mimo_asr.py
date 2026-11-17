"""MiMo single-audio ASR. BOX upload is buffered in bounded request RAM."""
import base64
import asyncio
import io
import json
import logging
import socket
import wave

import aiohttp
import httpx
import numpy as np

from .asr import ASRBase, ASRError, ASRModelLoadError, read_wav_16k_mono
from .mimo_tts import BASE_URL, _SSL, read_mimo_settings
from .http_stream_transport import cancellable_transport

logger = logging.getLogger("voice-bridge.mimo_asr")
MODEL = "mimo-v2.5-asr"


def pcm_signal(pcm):
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    size = int(samples.size)
    return dict(samples=size, duration_ms=round(size / 16, 3),
                peak=int(np.max(np.abs(samples))) if size else 0,
                rms=round(float(np.sqrt(np.mean(samples * samples))), 3) if size else 0.0,
                nonzero=int(np.count_nonzero(samples)),
                dc=round(float(np.mean(samples)), 3) if size else 0.0)


def _payload(pcm):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(pcm)
    return {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(audio.getvalue()).decode("ascii")}}
    ]}], "asr_options": {"language": "zh"}, "stream": False}


def _result(raw):
    try:
        value = json.loads(raw)
        if value.get("model") != MODEL or "error" in value:
            raise ValueError()
        text = value["choices"][0]["message"]["content"]
        if not isinstance(text, str) or len(text) > 16000:
            raise ValueError()
        return text.strip()
    except Exception:
        raise ASRError("MiMo ASR response contract invalid") from None


class AudioBuffer:
    def __init__(self, limit):
        self.pcm = bytearray()
        self.limit = limit
        self.closed = False

    def clear(self):
        self.pcm[:] = b"\x00" * len(self.pcm)
        self.pcm.clear()
        self.closed = True


class MiMoASR(ASRBase):
    name = "mimo"
    model = MODEL
    input_mode = "cloud_buffered"

    def __init__(self, max_bytes=480000, timeout=15):
        if not 0 < max_bytes <= 480000 or not 0 < timeout <= 30:
            raise ASRModelLoadError("Invalid MiMo ASR limits")
        self.max_bytes = int(max_bytes)
        self.timeout = float(timeout)
        self.last_call_ok = None
        try:
            self._key = read_mimo_settings()
        except Exception:
            raise ASRModelLoadError("MiMo project credential unavailable") from None

    def _check(self, pcm):
        if not pcm or len(pcm) % 2 or len(pcm) > self.max_bytes:
            raise ASRError("MiMo ASR PCM bounds invalid")

    def _failed_signal(self, pcm, category):
        logger.warning("MiMo ASR input_signal scope=whole_request category=%s metrics=%s", category, json.dumps(pcm_signal(pcm), sort_keys=True))

    def transcribe(self, wav_path):
        samples = read_wav_16k_mono(wav_path)
        pcm = (samples * 32768).astype("<i2").tobytes()
        self._check(pcm)
        try:
            with httpx.Client(trust_env=False, follow_redirects=False,
                              timeout=self.timeout, transport=cancellable_transport()) as client:
                with client.stream("POST", BASE_URL + "/chat/completions",
                                   headers={"api-key": self._key}, json=_payload(pcm)) as response:
                    if response.status_code != 200:
                        raise ASRError(f"MiMo ASR HTTP {response.status_code}")
                    raw = bytearray()
                    for part in response.iter_bytes():
                        raw.extend(part)
                        if len(raw) > 1024 * 1024:
                            raise ASRError("MiMo ASR response too large")
            text = _result(raw)
            self.last_call_ok = True
            if not text:
                self._failed_signal(pcm, "empty_text")
            return text
        except Exception as error:
            self.last_call_ok = False
            self._failed_signal(pcm, "cloud_error")
            if isinstance(error, ASRError):
                raise
            raise ASRError("MiMo ASR transport failed") from None


class MiMoBufferedASR(MiMoASR):
    async def transcribe_async(self, wav_source):
        samples = read_wav_16k_mono(wav_source)
        stream = self.create_stream()
        try:
            self.accept(stream, samples)
            return await self.final_async(stream)
        finally:
            stream.clear()

    def create_stream(self):
        return AudioBuffer(self.max_bytes)

    def accept(self, stream, samples):
        if stream.closed or len(stream.pcm) + samples.size * 2 > stream.limit:
            raise ASRError("MiMo ASR PCM bounds exceeded")
        if samples.dtype != np.float32 or not np.all(np.isfinite(samples)):
            raise ASRError("MiMo ASR sample contract invalid")
        stream.pcm.extend(np.clip(samples * 32768, -32768, 32767).astype("<i2").tobytes())

    def partial(self, stream):
        return ""  # The provider takes one complete audio input, not live PCM.

    async def final_async(self, stream):
        try:
            if not stream.pcm:
                self._failed_signal(stream.pcm, "empty_input")
                return ""
            self._check(stream.pcm)
            connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=_SSL)
            timeout = aiohttp.ClientTimeout(total=self.timeout, connect=3, sock_read=self.timeout)
            async with aiohttp.ClientSession(trust_env=False, connector=connector, timeout=timeout) as client:
                async with client.post(BASE_URL + "/chat/completions", headers={"api-key": self._key},
                                       json=_payload(stream.pcm), allow_redirects=False, ssl=_SSL) as response:
                    if response.status != 200:
                        raise ASRError(f"MiMo ASR HTTP {response.status}")
                    raw = bytearray()
                    async for part in response.content.iter_any():
                        raw.extend(part)
                        if len(raw) > 1024 * 1024:
                            raise ASRError("MiMo ASR response too large")
            text = _result(raw)
            self.last_call_ok = True
            if not text:
                self._failed_signal(stream.pcm, "empty_text")
            return text
        except Exception as error:
            self.last_call_ok = False
            self._failed_signal(stream.pcm, "cloud_error")
            if isinstance(error, ASRError):
                raise
            raise ASRError("MiMo ASR transport failed") from None
        finally:
            stream.clear()

    def close_stream(self, stream):
        stream.clear()

    async def final_for_request(self, stream, request):
        async def disconnected():
            while True:
                if await request.is_disconnected():
                    return
                await asyncio.sleep(.1)

        cloud = asyncio.create_task(self.final_async(stream))
        watch = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait({cloud, watch}, return_when=asyncio.FIRST_COMPLETED)
            if watch in done:
                raise asyncio.CancelledError()
            return cloud.result()
        finally:
            for task in (cloud, watch):
                if not task.done():
                    task.cancel()
            await asyncio.gather(cloud, watch, return_exceptions=True)
            stream.clear()
