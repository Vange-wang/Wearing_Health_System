"""ASR 抽象接口 + sherpa-onnx (SenseVoice) 实现（Spec §3/§4/§8）。

可插拔：换引擎只改 config + 新增一个 ASRBase 实现，业务代码不动。
"""
import logging
import wave
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

logger = logging.getLogger("voice-bridge.asr")


class ASRError(Exception):
    """ASR 阶段错误基类。"""


class ASRModelLoadError(ASRError):
    """模型加载失败 → 503 service_unavailable。"""


class ASRBase(ABC):
    @abstractmethod
    def transcribe(self, wav_path: Path) -> str:
        """WAV (16kHz/16bit/mono) → 中文文本。"""


def read_wav_16k_mono(wav_path: Path, sample_rate: int = 16000) -> np.ndarray:
    """读取并校验 WAV 为 float32 [-1,1]；格式不符抛 ValueError（由上层映射错误码）。"""
    with wave.open(str(wav_path), "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        fr = w.getframerate()
        nframes = w.getnframes()
        if nch != 1 or sw != 2 or fr != sample_rate:
            raise ValueError(
                f"bad_audio_format: channels={nch} sampwidth={sw} rate={fr} "
                f"(expect mono/16bit/{sample_rate})"
            )
        duration = nframes / fr
        if duration > 15:
            raise ValueError(f"audio_too_long: {duration:.1f}s > 15s")
        pcm = w.readframes(nframes)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return samples


class SherpaOnnxASR(ASRBase):
    def __init__(self, model_dir: Path, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        try:
            import sherpa_onnx
        except ImportError as e:
            raise ASRModelLoadError(f"sherpa-onnx 未安装: {e}") from e

        model_dir = Path(model_dir)
        model = model_dir / "model.int8.onnx"
        tokens = model_dir / "tokens.txt"
        if not model.exists() or not tokens.exists():
            raise ASRModelLoadError(f"模型文件缺失: {model_dir}（需 model.int8.onnx + tokens.txt）")

        try:
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model),
                tokens=str(tokens),
                use_itn=True,
                num_threads=2,
                debug=False,
            )
        except Exception as e:
            raise ASRModelLoadError(f"SenseVoice 加载失败: {e}") from e
        logger.info("ASR model loaded: %s", model_dir)

    def transcribe(self, wav_path: Path) -> str:
        samples = read_wav_16k_mono(wav_path, self.sample_rate)
        stream = self.recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, samples)
        self.recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        logger.info("ASR text (%d chars): %s", len(text), text[:80])
        return text


def create_asr(cfg) -> ASRBase:
    """工厂：按 config 创建 ASR 实例（当前仅 sherpa-onnx，换引擎改这里）。"""
    return SherpaOnnxASR(cfg.asr_model_dir, cfg.asr_sample_rate)
