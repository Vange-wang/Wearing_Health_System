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
from .llm import LLMError, TOOL_SENTINEL
from .router import HERMES, LIGHTWEIGHT, RAG

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
        lightweight_llm=None,
        router=None,
        rag=None,
        rag_top_k: int = 3,
        rag_score_threshold: float = 0.0,
    ):
        self.asr = asr
        self.llm = llm          # 慢路径 Hermes
        self.lightweight_llm = lightweight_llm  # 轻量通道 DeepSeek（可选）
        self.tts = tts
        self.vad = vad
        self.max_frame_bytes = int(max_frame_bytes)
        self.sentence_max_chars = int(sentence_max_chars)
        self.comfort_text = comfort_text
        self.router = router
        self.rag = rag
        self.rag_top_k = int(rag_top_k)
        self.rag_score_threshold = float(rag_score_threshold)
        self.timing: dict = {}

    def _init_timing(self):
        self.timing = {
            "asr_ms": None,
            "llm_ttft_ms": None,
            "llm_total_ms": None,
            "tts_first_ms": None,
            "tts_total_ms": None,
            "sentence_count": 0,
            "chunk_count": 0,
            # v0.3 分段计量 + 长期 RAG 路由（Spec §3/§4）
            "llm_backend": getattr(self.llm, "name", "unknown"),
            "tool_seen": False,
            "tool_ms": 0,
            "comfort_sent": False,
            "route": HERMES,
        }

    async def run(self, samples: np.ndarray, wav_path: Path):
        """批式路径（v0.2/v0.3 兼容）：VAD → 批式 ASR(SenseVoice) → 下游。"""
        self._init_timing()

        # 1. VAD
        if not self.vad.is_speech(samples):
            raise NoSpeechError("VAD 检测到静音/无效语音")

        # 2. ASR（批式）
        t = time.perf_counter()
        text = self.asr.transcribe(wav_path)
        self.timing["asr_ms"] = round((time.perf_counter() - t) * 1000)
        if not text:
            raise NoSpeechError("ASR 未识别出有效语音")

        async for frame in self._stream_from_text(text):
            yield frame

    async def run_text(self, text: str):
        """流式路径（v0.4 A2）：text 已由流式 ASR 给出，直接走下游（路由/LLM/TTS/帧）。"""
        self._init_timing()
        if not text:
            raise NoSpeechError("流式 ASR 未识别出有效语音")
        async for frame in self._stream_from_text(text):
            yield frame

    async def _stream_from_text(self, text: str):
        """text → 路由（轻量/RAG/Hermes）→ LLM 流 → 分句 → TTS → 长度前缀帧。"""
        # 路由判定 + RAG 检索（长期 RAG，Spec §3 A2 四步规则）
        rag_results: list[dict] = []
        if self.rag is not None:
            rag_results = self.rag.search(text, top_k=self.rag_top_k, score_threshold=self.rag_score_threshold)
        route = self.router.route(text, bool(rag_results)) if self.router else HERMES
        self.timing["route"] = route

        if route == HERMES:
            selected_llm = self.llm
            final_text = text
        else:
            selected_llm = self.lightweight_llm if self.lightweight_llm is not None else self.llm
            final_text = text
            if route == RAG and rag_results:
                ctx = "\n".join(
                    f"- {r['doc']['title']}: {r['doc']['text']}" for r in rag_results
                )
                final_text = f"【知识库参考，仅据以下内容回答】\n{ctx}\n\n用户问题：{text}"
        self.timing["llm_backend"] = getattr(selected_llm, "name", "unknown")

        # LLM 流 → 分句 → 逐句 TTS → 帧
        splitter = SentenceBuffer(max_chars=self.sentence_max_chars)
        llm_t0 = time.perf_counter()
        ttft_done = False
        tts_total_ms = 0.0
        sentence_count = 0
        chunk_count = 0
        comfort_sent = False

        # 轻量/DeepSeek 首步失败（USER.md 读失败 / 网络不可达）→ 降级慢路径（A2 兜底）
        try:
            delta_iter = selected_llm.stream_chat(final_text)
        except LLMError as e:
            if selected_llm is not self.llm:
                logger.warning("轻量通道失败(%s)，降级慢路径 Hermes", e)
                self.timing["route"] = HERMES
                self.timing["llm_backend"] = getattr(self.llm, "name", "unknown")
                delta_iter = self.llm.stream_chat(text)
            else:
                raise

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
            for delta in delta_iter:
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
            # 分段计量：工具期 ≈ 请求→首个正文 delta（工具期间无正文）
            stats = getattr(selected_llm, "stats", {}) or {}
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
