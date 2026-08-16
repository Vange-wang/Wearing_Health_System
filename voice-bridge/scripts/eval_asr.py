"""ASR 准确率基线评测（ISSUE-0007）。

用 edge 标准发音合成测试集（数字/体温/医学术语/口语），喂流式 ASR（zipformer），
输出参考 vs 识别对比，统计字符错误率（CER）与逐句判定，建立准确率基线。

用法：venv/Scripts/python.exe scripts/eval_asr.py
"""
import asyncio
import sys
import wave
import io
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.asr import create_streaming_asr
from app.tts import EdgeTTS


# 测试集：聚焦 ISSUE-0007 数字 / 体温 / 医学术语（「39度」→「三杀毒」重灾区）
TEST_SET = [
    ("发烧到三十九度怎么办", "数字+体温"),
    ("体温三十七点五度正常吗", "小数点体温"),
    ("我烧到三十八度了", "数字+体温"),
    ("今天三十九度", "数字"),
    ("心率一百二十算快吗", "术语+数字"),
    ("血氧饱和度九十八", "术语+数字"),
    ("血压一百二八十", "数字连读"),
    ("血糖五点六", "小数点"),
    ("我最近睡眠不好", "口语"),
    ("跑步后心率多少算正常", "口语+术语"),
    ("头疼怎么办", "口语"),
    ("胸口有点闷", "口语"),
    ("嗓子疼", "口语"),
    ("头晕", "口语"),
    ("今天天气怎么样", "闲聊对照"),
]


def _wav_to_samples(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        n = w.getnframes()
        pcm = w.readframes(n)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _cer(ref: str, hyp: str) -> float:
    """简化字符错误率（编辑距离 / 参考长度），无长文本故直接用 DP。"""
    r, h = list(ref), list(hyp)
    dp = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, len(h) + 1):
            cur = dp[j]
            dp[j] = min(
                dp[j] + 1,        # 删除
                dp[j - 1] + 1,    # 插入
                prev + (0 if r[i - 1] == h[j - 1] else 1),  # 替换
            )
            prev = cur
    return dp[len(h)] / max(1, len(r))


async def main():
    cfg = load_config()
    asr = create_streaming_asr(cfg)
    tts = EdgeTTS()

    print(f"{'判定':4s} | {'类型':12s} | 参考 -> 识别结果")
    print("-" * 70)

    total_cer = 0.0
    exact_ok = 0
    n = len(TEST_SET)
    CHUNK = 3200  # 100ms @16k

    for ref, label in TEST_SET:
        wav = await tts.synthesize(ref)
        samples = _wav_to_samples(wav)
        stream = asr.create_stream()
        for i in range(0, len(samples), CHUNK):
            asr.accept(stream, samples[i:i + CHUNK])
        hyp = asr.final(stream)
        cer = _cer(ref, hyp)
        total_cer += cer
        ok = (ref == hyp)
        exact_ok += (1 if ok else 0)
        mark = "OK " if ok else ("≈  " if cer < 0.3 else "ERR")
        print(f"{mark:4s} | {label:12s} | {ref} -> {hyp}  (CER={cer:.2f})")

    print("-" * 70)
    print(f"逐句完全一致: {exact_ok}/{n}")
    print(f"平均 CER: {total_cer / n:.3f}（越低越好，0=完全一致）")


if __name__ == "__main__":
    asyncio.run(main())
