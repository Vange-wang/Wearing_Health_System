"""流式流水线编排 + 长度前缀帧编码（Spec §5.3 / §6）。

Pipeline：VAD → ASR(批式) → LLM 流 → SentenceBuffer 分句 → 逐句 TTS → 长度前缀帧。
产出 `Iterator[bytes]`，每帧 = [4 字节大端长度] + [一句完整 WAV]。
解码接缝（A2）：契约是"PCM 16k/16bit/mono 进入 VAD/ASR"，M1 在 VAD 前插 opus→PCM 即可。
"""
import json
import logging
import struct
import time
from pathlib import Path

import numpy as np

from .splitter import SentenceBuffer
from .vad import VADGate
from .llm import TOOL_SENTINEL

logger = logging.getLogger("voice-bridge.pipeline")


class NoSpeechError(Exception):
    """VAD 拦截 / ASR 无有效语音 → 400 no_speech。"""


class FrameTooLargeError(Exception):
    """单帧超过最大帧长守卫 → 502（防损坏长度前缀导致客户端巨额分配）。"""


def encode_frame(wav: bytes, max_frame_bytes: int) -> bytes:
    """一句 WAV → 长度前缀帧（4 字节大端 uint32 + 载荷）。"""
    if len(wav) > max_frame_bytes:
        raise FrameTooLargeError(f"frame {len(wav)} bytes exceeds max {max_frame_bytes}")
    return struct.pack(">I", len(wav)) + wav


def decode_frame(data: bytes) -> tuple[bytes, bytes]:
    """解析一个长度前缀帧，返回 (载荷, 剩余字节)。数据不足时抛 ValueError。"""
    if len(data) < 4:
        raise ValueError("frame header incomplete")
    (n,) = struct.unpack(">I", data[:4])
    if len(data) < 4 + n:
        raise ValueError(f"frame payload incomplete: need {n}, have {len(data) - 4}")
    return data[4 : 4 + n], data[4 + n :]


class StreamingPipeline:
    """串联 VAD/ASR/LLM流/分句/TTS，产出长度前缀帧流。"""

    def __init__(
        self,
        asr,
        llm,
        tts,
        vad: VADGate,
        max_frame_bytes: int = 8 * 1024 * 1024,
        sentence_max_chars: int = 50,
        comfort_text: str = "好的，我查一下。",
    ):
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.vad = vad
        self.max_frame_bytes = int(max_frame_bytes)
        self.sentence_max_chars = int(sentence_max_chars)
        self.comfort_text = comfort_text
        self.timing: dict = {}

    async def run(self, samples: np.ndarray, wav_path: Path):
        """异步生成器：逐帧产出长度前缀帧 bytes。

        首帧产出前，所有"预期失败"（VAD/ASR/LLM/TTS）都以异常抛出，
        由路由在响应头发出前映射为错误状态码。
        """
        self.timing = {
            "asr_ms": None,
            "llm_ttft_ms": None,
            "llm_total_ms": None,
            "tts_first_ms": None,
            "tts_total_ms": None,
            "sentence_count": 0,
            "chunk_count": 0,
            # v0.3 分段计量（Spec §4）：tool_seen / tool_ms / llm_backend / comfort_sent
            "llm_backend": getattr(self.llm, "name", "unknown"),
            "tool_seen": False,
            "tool_ms": 0,
            "comfort_sent": False,
        }

        # 1. VAD
        if not self.vad.is_speech(samples):
            raise NoSpeechError("VAD 检测到静音/无效语音")

        # 2. ASR（批式，复用 v0.1 实现）
        t = time.perf_counter()
        text = self.asr.transcribe(wav_path)
        self.timing["asr_ms"] = round((time.perf_counter() - t) * 1000)
        if not text:
            raise NoSpeechError("ASR 未识别出有效语音")

        # 3. LLM 流 → 分句 → 逐句 TTS → 帧
        splitter = SentenceBuffer(max_chars=self.sentence_max_chars)
        llm_t0 = time.perf_counter()
        ttft_done = False
        tts_total_ms = 0.0
        sentence_count = 0
        chunk_count = 0
        comfort_sent = False

        async def _emit_sentence(sentence: str):
            nonlocal tts_total_ms, sentence_count, chunk_count
            t_start = time.perf_counter()
            wav = await self.tts.synthesize(sentence)
            dur_ms = (time.perf_counter() - t_start) * 1000
            if chunk_count == 0:
                self.timing["tts_first_ms"] = round(dur_ms)
            tts_total_ms += dur_ms
            sentence_count += 1
            chunk_count += 1
            return encode_frame(wav, self.max_frame_bytes)

        async def _emit_comfort():
            """安抚语第一帧（A5）：慢路径先给反馈，不计入正文句数。"""
            nonlocal tts_total_ms, chunk_count, comfort_sent
            t_start = time.perf_counter()
            wav = await self.tts.synthesize(self.comfort_text)
            dur_ms = (time.perf_counter() - t_start) * 1000
            if chunk_count == 0:
                self.timing["tts_first_ms"] = round(dur_ms)
            tts_total_ms += dur_ms
            chunk_count += 1
            comfort_sent = True
            self.timing["comfort_sent"] = True
            return encode_frame(wav, self.max_frame_bytes)

        try:
            for delta in self.llm.stream_chat(text):
                # 慢路径哨兵（工具调用）→ 立即发安抚语第一帧（A5）
                if delta is TOOL_SENTINEL:
                    if not comfort_sent:
                        yield await _emit_comfort()
                    continue
                if not ttft_done:
                    self.timing["llm_ttft_ms"] = round((time.perf_counter() - llm_t0) * 1000)
                    ttft_done = True
                for sentence in splitter.feed(delta):
                    yield await _emit_sentence(sentence)
        finally:
            # flush 剩余内容（即使无标点）
            for sentence in splitter.flush():
                yield await _emit_sentence(sentence)
            self.timing["llm_total_ms"] = round((time.perf_counter() - llm_t0) * 1000)
            self.timing["tts_total_ms"] = round(tts_total_ms)
            self.timing["sentence_count"] = sentence_count
            self.timing["chunk_count"] = chunk_count
            self.timing["comfort_sent"] = comfort_sent
            # v0.3 分段计量：工具期 ≈ 请求→首个正文 delta（工具期间无正文）
            stats = getattr(self.llm, "stats", {}) or {}
            tool_seen = bool(stats.get("tool_seen"))
            first_content_ms = stats.get("first_content_ms")
            self.timing["tool_seen"] = tool_seen
            if tool_seen and first_content_ms is not None:
                self.timing["tool_ms"] = (self.timing["asr_ms"] or 0) + first_content_ms
            else:
                self.timing["tool_ms"] = 0
            logger.info(json.dumps({
                "event": "stream_done",
                **{k: v for k, v in self.timing.items() if v is not None},
            }, ensure_ascii=False))
