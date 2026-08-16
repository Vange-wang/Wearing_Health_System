"""TTS 抽象接口 + edge-tts 实现（A5：edge 唯一，弃 piper）。

v0.4 A5 裁决：TTS 换 edge-tts 7.2.8（修复 403），弃 piper 兜底（edge 唯一）。
- edge-tts 7.2.8 输出 24kHz mp3（不再支持 output_format 自定义，7.x 移除）
- 解码链路：edge 合成 mp3 → miniaudio 解码（内嵌重采样到 16kHz/16bit/mono）→ 包 WAV
- edge 故障抛 TTSError（上层映射 502 upstream_error），**不兜底**（Spec §6.8）
"""
import asyncio
import io
import logging
import wave
from abc import ABC, abstractmethod

logger = logging.getLogger("voice-bridge.tts")


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


def _mp3_to_wav16k(mp3: bytes) -> bytes:
    """edge-tts 24kHz mp3 → miniaudio 解码重采样 → 16kHz/16bit/mono WAV。"""
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
    return wrap_pcm_as_wav(pcm, 16000)


class EdgeTTS(TTSBase):
    name = "edge"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def synthesize(self, text: str) -> bytes:
        import edge_tts

        last_err: Exception | None = None
        for attempt in range(2):  # 首次 + 1 次重试（缓解网络抖动/瞬时超时）
            try:
                chunks: list[bytes] = []
                communicate = edge_tts.Communicate(text=text, voice=self.voice)
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        chunks.append(chunk["data"])
            except Exception as e:
                # edge 故障（超时/断网）统一包装为 TTSError → 上层 502（Spec §6.8）
                last_err = TTSError(f"edge-tts 合成失败: {e}")
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


class TTSEngine:
    """edge 唯一（A5：弃 piper）。edge 故障抛 TTSError（上层 502），不兜底。

    保留 health() 上报（Spec §5.1）：configured_primary / active_engine 恒为 "edge"。
    """

    def __init__(self, primary: TTSBase):
        self.primary = primary
        self.configured_primary = primary.name
        self.active_engine = primary.name  # 恒 "edge"

    async def synthesize(self, text: str) -> bytes:
        return await self.primary.synthesize(text)  # 故障抛 TTSError → 502

    def health(self) -> dict:
        return {
            "configured_primary": self.configured_primary,
            "active_engine": self.active_engine,
        }


async def probe_edge(tts: TTSEngine, timeout: float = 3.0) -> None:
    """启动连通性预检（A5）：发最小合成请求，结果仅记录日志。

    edge 唯一（无兜底），探测失败不切引擎——请求时自然抛 TTSError → 502。
    """
    try:
        await asyncio.wait_for(tts.primary.synthesize("测试"), timeout=timeout)
        logger.info("edge probe OK, active_engine=edge")
    except Exception as e:
        logger.warning("edge probe failed: %s（edge 唯一，请求时将报 502）", e)


def create_tts(cfg) -> TTSEngine:
    """工厂：A5 起仅 edge 引擎（弃 piper）。"""
    if cfg.tts_primary != "edge":
        raise TTSError(f"未知 TTS 主引擎: {cfg.tts_primary}")
    return TTSEngine(EdgeTTS(cfg.tts_edge_voice))
