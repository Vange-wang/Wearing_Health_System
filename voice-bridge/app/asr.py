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
    """读取并校验 WAV 为 float32 [-1,1]；格式不符/损坏抛 ValueError（由上层映射错误码）。"""
    try:
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
    except ValueError:
        raise
    except Exception as e:
        # 损坏/非法 WAV（wave.Error、EOFError 等）→ 统一 bad_audio_format（Spec C1）
        raise ValueError(f"bad_audio_format: 无法解析 WAV（{e}）") from e
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


class StreamingASR:
    """流式 ASR（sherpa-onnx OnlineRecognizer，zipformer streaming，v0.4 A2）。

    边录边识别：accept() 喂 20ms PCM 分块，partial() 取实时结果；
    流结束（按键松开）调用 final() 拿最终结果。
    端点检测 = 按键松开（A3），故禁用内置静音端点检测。
    """

    def __init__(self, model_dir: Path, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        try:
            import sherpa_onnx
        except ImportError as e:
            raise ASRModelLoadError(f"sherpa-onnx 未安装: {e}") from e

        model_dir = Path(model_dir)
        files = {
            "encoder": model_dir / "encoder-epoch-99-avg-1.onnx",
            "decoder": model_dir / "decoder-epoch-99-avg-1.onnx",
            "joiner": model_dir / "joiner-epoch-99-avg-1.onnx",
            "tokens": model_dir / "tokens.txt",
            "bpe_vocab": model_dir / "bpe.vocab",
        }
        missing = [k for k, p in files.items() if not p.exists()]
        if missing:
            raise ASRModelLoadError(
                f"流式模型文件缺失: {model_dir}（缺 {', '.join(missing)}）"
            )
        try:
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(files["tokens"]),
                encoder=str(files["encoder"]),
                decoder=str(files["decoder"]),
                joiner=str(files["joiner"]),
                num_threads=2,
                sample_rate=sample_rate,
                feature_dim=80,
                decoding_method="greedy_search",
                modeling_unit="bpe",
                bpe_vocab=str(files["bpe_vocab"]),
                enable_endpoint_detection=False,  # 端点检测 = 按键松开（A3）
            )
        except Exception as e:
            raise ASRModelLoadError(f"流式 zipformer 加载失败: {e}") from e
        logger.info("Streaming ASR loaded: %s", model_dir)

    def create_stream(self):
        return self.recognizer.create_stream()

    def accept(self, stream, samples: np.ndarray):
        """喂一段 PCM float32 [-1,1]，并解码就绪帧。"""
        stream.accept_waveform(self.sample_rate, samples)
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)

    def partial(self, stream) -> str:
        return self.recognizer.get_result(stream).strip()

    def final(self, stream) -> str:
        """流结束（按键松开）：标记 input_finished，排空解码，返回最终文本。"""
        stream.input_finished()
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        return self.recognizer.get_result(stream).strip()


def create_streaming_asr(cfg) -> StreamingASR:
    return StreamingASR(cfg.asr_streaming_model_dir, cfg.asr_sample_rate)
