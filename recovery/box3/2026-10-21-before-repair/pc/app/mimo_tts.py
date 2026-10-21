"""MiMo preset streaming TTS, isolated new-file credential source, no fallback."""
import asyncio
import audioop
import base64
import io
import json
from pathlib import Path
import socket
import ssl
import wave
from contextlib import aclosing

import aiohttp
import certifi
from .tts import TTSError, TTSBase, wrap_pcm_as_wav

KEY_FILE = Path(__file__).resolve().parents[2] / ".env.cloud-tts"
BASE_URL = "https://api.xiaomimimo.com/v1"
MODEL = "mimo-v2.5-tts"
FIELDS = ("CLOUD_TTS_MIMO_API_KEY", "CLOUD_TTS_MIMO_BASE_URL", "CLOUD_TTS_MIMO_MODEL")
_SSL = ssl.create_default_context(cafile=certifi.where())


def read_mimo_settings(path=KEY_FILE):
    """Only the first three MiMo fields. Never buffer/read subsequent Volc values."""
    values = []
    try:
        with path.open("rb", buffering=0) as source:
            for expected in FIELDS:
                name = bytearray()
                while True:
                    byte = source.read(1)
                    if byte == b"=": break
                    if not byte or byte in (b"\r", b"\n") or len(name) > 64: raise ValueError()
                    name.extend(byte)
                if name.decode("ascii") != expected: raise ValueError()
                raw = bytearray()
                while True:
                    byte = source.read(1)
                    if byte in (b"", b"\n"): break
                    raw.extend(byte)
                    if len(raw) > 4096: raise ValueError()
                value = raw.decode("utf-8").strip()
                value = json.loads(value) if value.startswith('"') else value
                if not isinstance(value, str) or any(ord(c) < 32 for c in value): raise ValueError()
                values.append(value)
        if not values[0] or values[1:] != [BASE_URL, MODEL]: raise ValueError()
        return values[0]
    except Exception:
        raise TTSError("MiMo new-file configuration unavailable or invalid") from None


async def sse_data(chunks):
    buffer = bytearray(); fields = []; total = 0; event_bytes = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > 8*1024*1024: raise ValueError("STREAM_LIMIT")
        buffer.extend(chunk)
        if len(buffer) > 512*1024: raise ValueError("SSE_LINE_LIMIT")
        while b"\n" in buffer:
            line, _, rest = buffer.partition(b"\n"); buffer = bytearray(rest)
            line = line.rstrip(b"\r")
            if not line:
                if fields: yield b"\n".join(fields)
                fields = []; event_bytes = 0
            elif line.startswith(b"data:"):
                event_bytes += len(line)
                if event_bytes > 512*1024: raise ValueError("SSE_EVENT_LIMIT")
                fields.append(line[5:].lstrip(b" "))
    if buffer or fields: raise ValueError("SSE_TRUNCATED")


class MiMoTTS(TTSBase):
    name = "mimo"

    def __init__(self, voice="茉莉", timeout=15.0):
        if voice not in {"冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean", "mimo_default"}:
            raise TTSError("Unsupported MiMo preset voice")
        if not 0 < timeout <= 60: raise TTSError("Invalid MiMo timeout")
        self.voice = voice; self.timeout = timeout
        self._key = read_mimo_settings()

    async def stream_synthesize(self, text, min_segment_samples=800, later_min_segment_samples=4800):
        if min_segment_samples < 1 or later_min_segment_samples < 1:
            raise TTSError("Invalid MiMo segment threshold")
        carry = b""; state = None; pending = bytearray(); emitted = False; done = False; samples = 0
        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=3, sock_read=8)
        try:
            connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=_SSL)
            async with aiohttp.ClientSession(trust_env=False, connector=connector, timeout=timeout) as session:
                async with session.post(BASE_URL + "/chat/completions", headers={"api-key":self._key},
                    allow_redirects=False, ssl=_SSL,
                    json={"model":MODEL,"messages":[{"role":"assistant","content":text}],
                          "audio":{"format":"pcm16","voice":self.voice},"stream":True}) as response:
                    if response.status != 200: raise TTSError(f"MiMo HTTP {response.status}")
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise TTSError("MiMo response is not SSE")
                    async with aclosing(sse_data(response.content.iter_any())) as events:
                        async for payload in events:
                            if payload == b"[DONE]": done = True; break
                            value = json.loads(payload)
                            if "error" in value: raise TTSError("MiMo provider stream error")
                            for choice in value.get("choices", []):
                                audio = (choice.get("delta", {}).get("audio") or {}).get("data")
                                if not audio: continue
                                raw = carry + base64.b64decode(audio, validate=True)
                                length = len(raw)//2*2; carry, raw = raw[length:], raw[:length]
                                if not raw: continue
                                pcm, state = audioop.ratecv(raw,2,1,24000,16000,state)
                                samples += len(pcm)//2; pending.extend(pcm)
                                threshold = later_min_segment_samples if emitted else min_segment_samples
                                if len(pending)//2 >= threshold:
                                    segment = wrap_pcm_as_wav(bytes(pending),16000); pending.clear(); emitted = True
                                    yield segment
                    if not done or carry or not samples: raise TTSError("MiMo incomplete PCM stream")
                    if pending: yield wrap_pcm_as_wav(bytes(pending),16000)
        except asyncio.CancelledError:
            raise
        except TTSError:
            raise
        except Exception as error:
            raise TTSError(f"MiMo streaming synthesis failed: {type(error).__name__}") from None

    async def synthesize(self, text):
        from contextlib import aclosing
        pcm = bytearray()
        async with aclosing(self.stream_synthesize(text)) as stream:
            async for segment in stream:
                with wave.open(io.BytesIO(segment),"rb") as wav:
                    pcm.extend(wav.readframes(wav.getnframes()))
        if not pcm: raise TTSError("MiMo empty PCM")
        return wrap_pcm_as_wav(bytes(pcm),16000)
