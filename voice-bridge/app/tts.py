"""TTS 抽象接口 + edge-tts / piper 实现（含自动兜底，Spec §3/§4/§9）。

可插拔：换引擎只改 config + 新增 TTSBase 实现，业务代码不动。
- 主引擎 edge-tts：联网，output_format 指定 16kHz/16bit/mono PCM，直接出 WAV
- 兜底 piper：离线，输出原始 PCM（onnx.json 采样率），用标准库 audioop 重采样到 16kHz
  （audioop 是 Python 3.11 标准库，零新增依赖）
"""
import asyncio
import audioop
import io
import logging
import os
import sys
import wave
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("voice-bridge.tts")

# piper-tts 1.6.0 Windows wheel 的 espeak-ng-data 查找用了编译机硬编码路径（打包 bug），
# 在 import piper 前用官方支持的环境变量指到 venv 内真实数据目录。
_piper_data = (
    Path(sys.executable).resolve().parent.parent
    / "Lib" / "site-packages" / "piper" / "espeak-ng-data"
)
if _piper_data.exists():
    os.environ.setdefault("PIPER_ESPEAKNG_DATA_DIRECTORY", str(_piper_data))


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


class EdgeTTS(TTSBase):
    name = "edge"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def synthesize(self, text: str) -> bytes:
        import edge_tts

        # edge-tts 6.1.x 不支持 output_format 参数；venv 内 edge_tts/communicate.py
        # 已做 vendor patch：outputFormat 改为 riff-16khz-16bit-mono-pcm（直接出 16k WAV）
        chunks: list[bytes] = []
        communicate = edge_tts.Communicate(text=text, voice=self.voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        if not chunks:
            raise TTSError("edge-tts 返回空音频")
        logger.info("edge-tts synthesized: %d bytes", sum(len(c) for c in chunks))
        return b"".join(chunks)


class PiperTTS(TTSBase):
    name = "piper"

    def __init__(self, model_path: Path, config_path: Path):
        model_path = Path(model_path)
        config_path = Path(config_path)
        if not model_path.exists():
            raise TTSError(f"piper 模型缺失: {model_path}")
        try:
            from piper import PiperVoice
        except ImportError as e:
            raise TTSError(f"piper-tts 未安装: {e}") from e
        # piper-tts 1.6.0 Windows wheel 的 espeak 数据默认走编译机硬编码路径（打包 bug），
        # 显式传 venv 内真实数据目录修复
        self.voice = PiperVoice.load(
            str(model_path),
            config_path=str(config_path),
            espeak_data_dir=str(_piper_data),
        )
        self.sample_rate = self.voice.config.sample_rate
        logger.info("piper loaded: %s (sr=%d)", model_path, self.sample_rate)

    def _synthesize_sync(self, text: str) -> bytes:
        chunks = []
        for chunk in self.voice.synthesize(text):
            chunks.append(chunk.audio_int16_bytes)
        pcm = b"".join(chunks)
        if not pcm:
            raise TTSError("piper 返回空音频")
        if self.sample_rate != 16000:
            pcm = audioop.ratecv(pcm, 2, 1, self.sample_rate, 16000, None)[0]
        return wrap_pcm_as_wav(pcm, 16000)

    async def synthesize(self, text: str) -> bytes:
        # piper 是同步 CPU 推理，放线程池避免阻塞事件循环
        return await asyncio.to_thread(self._synthesize_sync, text)


class TTSEngine:
    """主引擎 + 自动兜底（Spec：edge 失败自动切 piper，日志有 fallback 记录）。"""

    def __init__(self, primary: TTSBase, fallback: TTSBase | None):
        self.primary = primary
        self.fallback = fallback

    async def synthesize(self, text: str) -> bytes:
        try:
            return await self.primary.synthesize(text)
        except Exception as e:
            if self.fallback is None:
                raise TTSError(f"{self.primary.name} 失败且无兜底: {e}") from e
            logger.warning(
                "TTS fallback: %s failed (%s), switching to %s",
                self.primary.name, e, self.fallback.name,
            )
            return await self.fallback.synthesize(text)


def create_tts(cfg) -> TTSEngine:
    """工厂：按 config 创建主引擎 + 兜底。piper 缺失/装不上时兜底为 None（降级运行，health 可见）。"""
    primary: TTSBase = EdgeTTS(cfg.tts_edge_voice) if cfg.tts_primary == "edge" else None
    if primary is None:
        raise TTSError(f"未知 TTS 主引擎: {cfg.tts_primary}")

    fallback = None
    if cfg.tts_fallback == "piper":
        try:
            fallback = PiperTTS(cfg.tts_piper_model, cfg.tts_piper_config)
        except TTSError as e:
            logger.warning("piper 兜底不可用: %s", e)
    return TTSEngine(primary, fallback)
