"""VAD 能量门限（Spec §6.4，OI-007 计划覆盖）。

读取 float32 PCM 分帧（10ms/frame @16kHz）→ 每帧 RMS → 连续 speech 帧数判断。
零新增依赖：numpy 已在 sherpa-onnx 依赖链中。
"""
import logging

import numpy as np

logger = logging.getLogger("voice-bridge.vad")


class VADGate:
    """能量门限 VAD。

    - `rms_threshold`：单帧 RMS 达到该阈值即判为 speech 帧
    - `min_speech_frames`：连续 speech 帧数下限（低于此 → 判 no_speech）
    """

    def __init__(
        self,
        enabled: bool = True,
        rms_threshold: float = 0.005,
        min_speech_frames: int = 10,
        frame_ms: int = 10,
        sample_rate: int = 16000,
    ):
        self.enabled = enabled
        self.rms_threshold = float(rms_threshold)
        self.min_speech_frames = int(min_speech_frames)
        self.frame_len = int(sample_rate * frame_ms / 1000)  # 160 @ 16kHz

    def is_speech(self, samples: np.ndarray) -> bool:
        """samples: float32 [-1,1] 单声道。返回是否含有效语音。"""
        if not self.enabled:
            return True  # VAD 关闭时直接放行（Spec §5.1 vad=disabled）

        frame_len = self.frame_len
        n = len(samples) // frame_len
        if n == 0:
            logger.info("VAD: 样本过短（%d 样本，不足 1 帧），判 no_speech", len(samples))
            return False

        frames = samples[: n * frame_len].reshape(n, frame_len)
        rms = np.sqrt(np.mean(frames * frames, axis=1))
        speech = rms >= self.rms_threshold

        # 连续 speech 帧数统计（取最长连续段）
        best = cur = 0
        for s in speech:
            if s:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0

        ok = best >= self.min_speech_frames
        logger.info(
            "VAD: frames=%d speech_peak=%d frames (>=%d)=%s max_rms=%.5f",
            n, best, self.min_speech_frames, ok, float(rms.max()) if n else 0.0,
        )
        return ok
