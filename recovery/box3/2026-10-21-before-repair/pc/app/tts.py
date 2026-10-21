"""TTS 抽象接口 + edge-tts 实现（A5：edge 唯一，弃 piper）。

v0.4 A5 裁决：TTS 换 edge-tts 7.2.8（修复 403），弃 piper 兜底（edge 唯一）。
- edge-tts 7.2.8 输出 24kHz mp3（不再支持 output_format 自定义，7.x 移除）
- 解码链路：edge 合成 mp3 → miniaudio 解码（内嵌重采样到 16kHz/16bit/mono）→ 包 WAV
- edge 故障抛 TTSError（上层映射 502 upstream_error），**不兜底**（Spec §6.8）
"""
import asyncio
import io
import logging
import socket
import ssl
import wave
from abc import ABC, abstractmethod
from contextlib import aclosing

import aiohttp
import certifi
from .edge_connection import owned_communicate

# vendored 最小协议（方向1 预连接）：复用 edge-tts 内部的 wire 协议函数，
# 只做「建 WSS + 发 speech.config」，把「发 ssml」推迟到首句到达，与 LLM 生成并行。
from edge_tts.communicate import (  # noqa: E402
    connect_id,
    date_to_string,
    escape,
    get_headers_and_data,
    mkssml,
    remove_incompatible_characters,
    split_text_by_byte_length,
    ssml_headers_plus_data,
)
from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL  # noqa: E402
from edge_tts.data_classes import TTSConfig  # noqa: E402
from edge_tts.drm import DRM  # noqa: E402

logger = logging.getLogger("voice-bridge.tts")

# 与 edge_tts.communicate._SSL_CTX 一致（certifi 证书，避免系统证书缺失导致握手失败）
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _ipv4_connector() -> aiohttp.TCPConnector:
    """强制 IPv4 的连接器。

    edge-tts 用 aiohttp 默认 IPv6 优先（family=0），但 iPhone 热点等环境 IPv6 不通，
    导致连 speech.platform.bing.com 失败（「指定的网络名不再可用」）。强制 AF_INET 解决。
    """
    return aiohttp.TCPConnector(family=socket.AF_INET)


class TTSError(Exception):
    """TTS 阶段错误基类。"""


def wrap_pcm_as_wav(pcm: bytes, sample_rate: int) -> bytes:
    """16bit/mono PCM 包成 WAV bytes。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class TTSBase(ABC):
    name: str

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """文本 → WAV bytes（16kHz/16bit/mono）。"""


def _trim_silence(wav: bytes, keep_ms: int = 50) -> bytes:
    """裁剪 WAV 前后静音（edge 音频自带 ~0.19s 前导 + ~0.57s 尾静音，是句间间隔的主因）。

    前后各保留 keep_ms 毫秒缓冲，避免把语音起音/收音截得太生硬。
    """
    import numpy as np

    with wave.open(io.BytesIO(wav)) as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16)
    if samples.size == 0:
        return wav
    peak = int(np.max(np.abs(samples)))
    if peak == 0:
        return wav  # 全静音，保留原样
    threshold = max(200, int(peak * 0.02))
    idx = np.nonzero(np.abs(samples) > threshold)[0]
    if idx.size == 0:
        return wav
    keep = int(sr * keep_ms / 1000)
    start = max(0, int(idx[0]) - keep)
    end = min(samples.size, int(idx[-1]) + 1 + keep)
    if start >= end:
        return wav
    return wrap_pcm_as_wav(samples[start:end].astype(np.int16).tobytes(), sr)


def _mp3_to_wav16k(mp3: bytes) -> bytes:
    """edge-tts 24kHz mp3 → miniaudio 解码重采样 → 16kHz/16bit/mono WAV（裁静音）。"""
    import miniaudio

    dec = miniaudio.decode(
        mp3,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=16000,
    )
    pcm = dec.samples.tobytes() if hasattr(dec.samples, "tobytes") else bytes(dec.samples)
    if not pcm:
        raise TTSError("miniaudio 解码结果为空")
    return _trim_silence(wrap_pcm_as_wav(pcm, 16000))


def _speech_config_msg() -> str:
    """speech.config 消息（与 edge_tts.communicate.__stream 的 send_command_request 一致）。"""
    return (
        f"X-Timestamp:{date_to_string()}\r\n"
        "Content-Type:application/json; charset=utf-8\r\n"
        "Path:speech.config\r\n\r\n"
        '{"context":{"synthesis":{"audio":{"metadataoptions":{'
        '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
        "},"
        '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"'
        "}}}}\r\n"
    )


class _EdgePreconnect:
    """预建好的 edge WSS 连接（已发 speech.config），供首句发 ssml 流式合成。

    方向1（延迟优化）：建连（~0.65s）与 LLM 首句生成并行，首句到达即发 ssml，
    净等待降到 ~0.75s，省掉每句都付的建连成本。
    """

    def __init__(self, session, ws, tts_config: TTSConfig):
        self._session = session
        self._ws = ws
        self._tts_config = tts_config
        self._closed = False
        self._close_task = None
        self._close_steps = {}
        self._step_closed = set()
        self._close_callbacks = []
        self._close_timeout = 2.0  # cleanup only; no change to synthesis timeouts

    def _wire_ssml(self, text: str) -> str:
        # 与 edge_tts.Communicate.__init__ 相同的文本处理链（escape + 去不兼容字符 + 分片）
        escaped = escape(remove_incompatible_characters(text))
        parts = list(split_text_by_byte_length(escaped, 4096))
        return mkssml(self._tts_config, parts[0])

    async def stream_synthesize(
        self,
        text: str,
        min_segment_samples: int = 800,
        later_min_segment_samples: int = 4800,
    ):
        """用预建连接发 ssml，流式解码 yield WAV 段（与 EdgeTTS.stream_synthesize 对齐）。"""
        import miniaudio

        mp3_buf = b""
        emitted = 0
        first_sent = False
        got_audio = False
        try:
            await self._ws.send_str(
                ssml_headers_plus_data(connect_id(), date_to_string(), self._wire_ssml(text))
            )
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY and len(msg.data) >= 2:
                    hlen = int.from_bytes(msg.data[:2], "big")
                    params, data = get_headers_and_data(msg.data, hlen)
                    if params.get(b"Path") == b"audio" and data:
                        got_audio = True
                        mp3_buf += data
                        try:
                            dec = miniaudio.decode(
                                mp3_buf,
                                output_format=miniaudio.SampleFormat.SIGNED16,
                                nchannels=1,
                                sample_rate=16000,
                            )
                        except Exception:
                            continue  # 首段 mp3 尚不足以解码，等下个 chunk
                        samples = dec.samples
                        new_n = len(samples) - emitted
                        threshold = later_min_segment_samples if first_sent else min_segment_samples
                        if new_n >= threshold:
                            yield wrap_pcm_as_wav(samples[emitted:].tobytes(), 16000)
                            emitted = len(samples)
                            first_sent = True
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    d = msg.data.encode("utf-8")
                    params, _ = get_headers_and_data(d, d.find(b"\r\n\r\n"))
                    if params.get(b"Path") == b"turn.end":
                        break
        except Exception as e:
            raise TTSError(f"edge 预连接流式合成失败: {type(e).__name__}") from None
        # flush 剩余（含整句不足首段阈值的情况）
        if mp3_buf:
            try:
                dec = miniaudio.decode(
                    mp3_buf,
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=1,
                    sample_rate=16000,
                )
                full = dec.samples
                if len(full) > emitted:
                    yield wrap_pcm_as_wav(full[emitted:].tobytes(), 16000)
            except Exception as e:
                raise TTSError(f"edge 预连接流式 flush 解码失败: {type(e).__name__}") from None
        if not got_audio:
            raise TTSError("edge 预连接未收到音频")

    async def close(self) -> None:
        if self._closed:
            return
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(self._close_impl())
            self._close_task.add_done_callback(self._close_done)
        await asyncio.shield(self._close_task)

    @property
    def quiescent(self):
        return self._closed and all(task.done() for task in self._close_steps.values())

    def when_quiescent(self, callback):
        self._close_callbacks.append(callback)
        self._notify_close()

    def _notify_close(self):
        if self.quiescent:
            callbacks, self._close_callbacks = self._close_callbacks, []
            for callback in callbacks:
                callback()

    def _close_done(self, task):
        if not task.cancelled():
            failure = task.exception()  # observe abandoned caller's cleanup failure
            if failure is None:
                for name, step in self._close_steps.items():
                    if step is task:
                        self._step_closed.add(name)
                self._closed = len(self._step_closed) == 2
        self._notify_close()

    async def _close_step(self, name, resource):
        if name in self._step_closed:
            return
        task = self._close_steps.get(name)
        if task is not None and task.done() and not task.cancelled() and task.exception() is None:
            self._step_closed.add(name)
            return
        if task is None or task.done():
            task = asyncio.create_task(resource.close())
            self._close_steps[name] = task
            task.add_done_callback(self._close_done)
        done, _ = await asyncio.wait({task}, timeout=self._close_timeout)
        if not done:
            task.cancel()
            # Do not join a third-party close that ignores cancellation. Keep
            # the actual task visible; it is not a completed resource/lease.
            raise TimeoutError(f"edge {name} cleanup pending")
        task.result()
        self._step_closed.add(name)

    async def _close_impl(self):
        failure = None
        try:
            await self._close_step("ws", self._ws)
        except BaseException as exc:
            failure = exc
        try:
            await self._close_step("session", self._session)
        except BaseException as exc:
            if failure is None:
                failure = exc
        self._closed = len(self._step_closed) == 2
        self._notify_close()
        if failure is not None:
            raise failure


class EdgeTTS(TTSBase):
    name = "edge"

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "-5%",
        pitch: str = "+0Hz",
        proxy: str = "",
    ):
        if not SEC_MS_GEC_VERSION.startswith("2-"):
            raise TTSError("Edge protocol v2 dependency required")
        self.voice = voice
        self.rate = rate    # 语速稍慢 5%，更像从容说话（人设情感化，Hermes 起草）
        self.pitch = pitch  # 音调默认；想更活泼可 +3Hz
        self.proxy = proxy  # Explicit URL for profile A; empty string means direct, never env proxy.

    async def synthesize(self, text: str) -> bytes:
        import edge_tts

        last_err: Exception | None = None
        for attempt in range(2):  # 首次 + 1 次重试（缓解网络抖动/瞬时超时）
            try:
                chunks: list[bytes] = []
                async with owned_communicate(edge_tts.Communicate, text=text,
                                             voice=self.voice, rate=self.rate,
                                             pitch=self.pitch, proxy=self.proxy) as communicate:
                    async with aclosing(communicate.stream()) as stream:
                        async for chunk in stream:
                            if chunk["type"] == "audio":
                                chunks.append(chunk["data"])
            except Exception as e:
                # edge 故障（超时/断网）统一包装为 TTSError → 上层 502（Spec §6.8）
                last_err = TTSError(f"edge-tts 合成失败: {type(e).__name__}")
                logger.warning("edge 合成失败（第 %d 次），%s", attempt + 1, last_err)
                if attempt == 0:
                    await asyncio.sleep(0.3)
                continue
            mp3 = b"".join(chunks)
            if not mp3:
                last_err = TTSError("edge-tts 返回空音频")
                if attempt == 0:
                    await asyncio.sleep(0.3)
                continue
            return _mp3_to_wav16k(mp3)
        raise last_err or TTSError("edge-tts 合成失败")

    async def stream_synthesize(
        self,
        text: str,
        min_segment_samples: int = 800,
        later_min_segment_samples: int = 4800,
    ):
        """方案2（延迟优化）：流式合成，yield 多段 WAV，首段在首 chunk 到达即产出。

        原理：edge `stream()` 边合成边返回 mp3 chunk；miniaudio 对「累积的 mp3」可分段解码，
        且前缀 100% 一致（实测），故每累积到阈值即发一段增量 PCM。
        - 首段阈值小（50ms）：首 chunk 到达即发首帧，压低首响延迟。
        - 后续段阈值大（300ms）：减少帧数，避免固件逐帧播放的断续。

        注意：流式不裁静音（edge 前导 ~0.19s 会进入首段），接受；句间间隔由 pipeline 保证。
        """
        import edge_tts
        import miniaudio

        mp3_buf = b""
        emitted = 0  # 已产出的 sample 数（增量游标，靠解码前缀一致性保证无重复/无缺口）
        first_sent = False
        try:
            async with owned_communicate(edge_tts.Communicate, text=text,
                                         voice=self.voice, rate=self.rate,
                                         pitch=self.pitch, proxy=self.proxy) as communicate:
                async with aclosing(communicate.stream()) as stream:
                    async for chunk in stream:
                        if chunk["type"] != "audio":
                            continue
                        mp3_buf += chunk["data"]
                        try:
                            dec = miniaudio.decode(
                                mp3_buf,
                                output_format=miniaudio.SampleFormat.SIGNED16,
                                nchannels=1,
                                sample_rate=16000,
                            )
                        except Exception:
                            continue  # 首段 mp3 尚不足以解码，等下个 chunk
                        samples = dec.samples
                        new_n = len(samples) - emitted
                        threshold = later_min_segment_samples if first_sent else min_segment_samples
                        if new_n >= threshold:
                            yield wrap_pcm_as_wav(samples[emitted:].tobytes(), 16000)
                            emitted = len(samples)
                            first_sent = True
        except Exception as e:
            raise TTSError(f"edge-tts 流式合成失败: {type(e).__name__}") from None
        # flush 剩余（含整句不足首段阈值的情况）
        if mp3_buf:
            try:
                dec = miniaudio.decode(
                    mp3_buf,
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=1,
                    sample_rate=16000,
                )
                full = dec.samples
                if len(full) > emitted:
                    yield wrap_pcm_as_wav(full[emitted:].tobytes(), 16000)
            except Exception as e:
                raise TTSError(f"edge 流式 flush 解码失败: {type(e).__name__}") from None

    async def open_preconnect(self, timeout: float = 2.0):
        """方向1：预建 WSS + 发 speech.config（与 LLM 首句生成并行），返回可复用连接。

        - trust_env=False：不读环境代理变量（AGENTS.md「任何环境不得配置代理」红线）。
        - 失败返回 None，上层无缝回退「用时建连」路径，无正确性风险。
        """
        session = aiohttp.ClientSession(trust_env=False, connector=_ipv4_connector())
        try:
            ws = await asyncio.wait_for(
                session.ws_connect(
                    f"{WSS_URL}&ConnectionId={connect_id()}"
                    f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
                    f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
                    compress=15,
                    proxy=self.proxy,
                    headers=DRM.headers_with_muid(WSS_HEADERS),
                    ssl=_SSL_CTX,
                ),
                timeout,
            )
            await ws.send_str(_speech_config_msg())
            tts_config = TTSConfig(self.voice, self.rate, "+0%", self.pitch, "SentenceBoundary")
            return _EdgePreconnect(session, ws, tts_config)
        except asyncio.CancelledError:
            await session.close()
            raise
        except Exception as e:
            logger.warning("edge 预连接失败，回退用时建连: %s", type(e).__name__)
            try:
                await session.close()
            except Exception:
                pass
            return None


class TTSEngine:
    """edge 唯一（A5：弃 piper）。edge 故障抛 TTSError（上层 502），不兜底。

    保留 health() 上报（Spec §5.1）：configured_primary / active_engine 恒为 "edge"。
    """

    def __init__(self, primary: TTSBase, probe_timeout: float = 5.0):
        self.primary = primary
        self.configured_primary = primary.name
        self.active_engine = primary.name  # 恒 "edge"
        self.probe_timeout = probe_timeout
        # 需求1：真实探活状态（active_engine 恒真不可用，需真实合成探测）
        self.last_probe_ok: bool | None = None
        self.last_probe_ts: float | None = None
        self._health_serial = self._health_applied = self._failures = 0
        self._health_changed = asyncio.Event()
        self.last_failure_ts = self.last_failure_category = None
        self.last_probe_event_ok = self.last_probe_event_ts = None

    def _begin_health_call(self):
        self._health_serial += 1
        return self._health_serial

    def _record_health(self, serial, ok, category=None, *, probe=False):
        import time
        stamp = time.time()
        if not ok:
            self.last_failure_ts, self.last_failure_category = stamp, category
        if probe:
            self.last_probe_event_ok, self.last_probe_event_ts = ok, stamp
        if serial < self._health_applied:
            return
        self._health_applied = serial
        self.last_probe_ok, self.last_probe_ts = ok, stamp
        self._failures = 0 if ok else self._failures + 1
        self._health_changed.set()

    def recovery_delay(self, healthy_interval):
        return healthy_interval if self.last_probe_ok is True else min(30, 2 ** min(5, max(1, self._failures)))

    async def maintain_health(self, healthy_interval):
        while True:
            self._health_changed.clear()
            try:
                await asyncio.wait_for(self._health_changed.wait(), self.recovery_delay(healthy_interval))
            except asyncio.TimeoutError:
                await self.probe()

    async def synthesize(self, text: str) -> bytes:
        serial = self._begin_health_call()
        try:
            audio = await self.primary.synthesize(text)
            if not audio:
                raise TTSError("TTS empty audio")
        except Exception as exc:
            self._record_health(serial, False, type(exc).__name__)
            raise
        self._record_health(serial, True)
        return audio

    def stream_synthesize(self, text: str, min_segment_samples: int = 800):
        """方案2：流式合成（返回 async generator），供 pipeline 边收边发帧。"""
        async def stream():
            serial = self._begin_health_call()
            emitted = False
            try:
                async with aclosing(self.primary.stream_synthesize(text, min_segment_samples)) as segments:
                    async for segment in segments:
                        if segment and not emitted:
                            emitted = True
                            self._record_health(serial, True)
                        yield segment
                if not emitted:
                    raise TTSError("TTS empty stream")
            except TTSError as exc:
                self._record_health(serial, False, type(exc).__name__)
                raise
            except Exception as exc:
                self._record_health(serial, False, type(exc).__name__)
                raise TTSError(f"TTS 流式合成失败: {type(exc).__name__}") from None

        return stream()

    async def open_preconnect(self, timeout: float = 2.0):
        """方向1：预建连接（委托 primary）。primary 不支持时返回 None。"""
        if hasattr(self.primary, "open_preconnect"):
            return await self.primary.open_preconnect(timeout)
        return None

    def health(self) -> dict:
        return {
            "configured_primary": self.configured_primary,
            "active_engine": self.active_engine,
            # 需求1：真实探活结果（供固件状态灯判断 TTS 是否可用）
            "last_probe_ok": self.last_probe_ok,
            "last_probe_ts": self.last_probe_ts,
            "last_failure_ts": self.last_failure_ts,
            "last_failure_category": self.last_failure_category,
            "last_probe_event_ok": self.last_probe_event_ok,
            "last_probe_event_ts": self.last_probe_event_ts,
        }

    async def probe(self, timeout: float | None = None) -> bool:
        """需求1：真实合成探测一次，更新 last_probe_ok / last_probe_ts。

        返回是否探测成功。edge 故障时置 False（供 health 上报，固件据此灭灯）。
        """
        serial = self._begin_health_call()
        try:
            audio = await asyncio.wait_for(self.primary.synthesize("测试"), timeout=self.probe_timeout if timeout is None else timeout)
            if not audio:
                raise TTSError("TTS empty probe")
        except Exception as exc:
            self._record_health(serial, False, type(exc).__name__, probe=True)
            return False
        self._record_health(serial, True, probe=True)
        return True


async def probe_edge(tts: TTSEngine, timeout: float = 3.0) -> None:
    """启动连通性预检（A5 + 需求1）：发最小合成请求，更新 last_probe_ok/ts。

    edge 唯一（无兜底），探测失败不切引擎——请求时自然抛 TTSError → 502。
    需求1：探测结果写入 tts.last_probe_ok/ts，供 health 上报（固件状态灯判 TTS 可用）。
    """
    ok = await tts.probe(timeout)
    if ok:
        logger.info("%s probe OK, active_engine=%s", tts.active_engine, tts.active_engine)
    else:
        logger.warning("%s probe failed（请求时将报 502）", tts.active_engine)


def create_tts(cfg) -> TTSEngine:
    """工厂：A5 起仅 edge 引擎（弃 piper）。"""
    if cfg.tts_primary == "mimo":
        from .mimo_tts import MiMoTTS
        return TTSEngine(MiMoTTS(cfg.tts_mimo_voice, cfg.tts_mimo_timeout), probe_timeout=cfg.tts_probe_timeout)
    if cfg.tts_primary != "edge":
        raise TTSError(f"未知 TTS 主引擎: {cfg.tts_primary}")
    return TTSEngine(
        EdgeTTS(cfg.tts_edge_voice, cfg.tts_edge_rate, cfg.tts_edge_pitch,
                proxy=getattr(cfg, "tts_edge_proxy", ""))
    )
