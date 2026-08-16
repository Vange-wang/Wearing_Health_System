"""流式流水线编排 + 长度前缀帧编码（Spec §5.3 / §6）。

Pipeline：VAD → ASR(批式) → LLM 流 → SentenceBuffer 分句 → 逐句 TTS → 长度前缀帧。
产出 `Iterator[bytes]`，每帧 = [4 字节大端长度] + [一句完整 WAV]。
解码接缝（A2）：契约是"PCM 16k/16bit/mono 进入 VAD/ASR"，M1 在 VAD 前插 opus→PCM 即可。
"""
import asyncio
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
        sentence_gap_ms: int = 300,
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
        self.sentence_gap_ms = int(sentence_gap_ms)  # A6 句间停顿
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

        # 预合成流水线：produce(LLM 分句) → tts_queue → worker(TTS) → frame_queue → 主流程发帧
        # 收益：TTS 合成与 LLM 生成并行，句间仅剩 A6 停顿（300ms），不再累加 edge 合成 ~1.3s
        tts_queue: asyncio.Queue = asyncio.Queue()
        frame_queue: asyncio.Queue = asyncio.Queue()
        tts_first_recorded = False
        comfort_queued = False

        async def _worker():
            nonlocal tts_total_ms, sentence_count, chunk_count, comfort_sent, tts_first_recorded
            while True:
                item = await tts_queue.get()
                if item is None:
                    await frame_queue.put(None)
                    break
                kind, sentence = item
                t_start = time.perf_counter()
                try:
                    wav = await self.tts.synthesize(sentence)
                except Exception as e:
                    logger.error("预合成 TTS 失败（跳过该句）: %s", e)
                    continue
                dur_ms = (time.perf_counter() - t_start) * 1000
                if not tts_first_recorded:
                    self.timing["tts_first_ms"] = round(dur_ms)
                    tts_first_recorded = True
                tts_total_ms += dur_ms
                if kind == "comfort":
                    comfort_sent = True
                    self.timing["comfort_sent"] = True
                else:
                    sentence_count += 1
                chunk_count += 1
                await frame_queue.put(encode_frame(wav, self.max_frame_bytes))

        async def _produce():
            nonlocal ttft_done, comfort_queued
            # LLM 同步流式迭代放到线程池，避免阻塞事件循环（否则 worker 无法并行 TTS）
            it = iter(delta_iter)
            sentinel = object()

            def _next_delta():
                try:
                    return next(it)
                except StopIteration:
                    return sentinel

            try:
                while True:
                    delta = await asyncio.to_thread(_next_delta)
                    if delta is sentinel:
                        break
                    # 慢路径哨兵（工具调用）→ 安抚语优先合成（A5）
                    if delta is TOOL_SENTINEL:
                        if not comfort_queued:
                            await tts_queue.put(("comfort", self.comfort_text))
                            comfort_queued = True
                        continue
                    if not ttft_done:
                        self.timing["llm_ttft_ms"] = round((time.perf_counter() - llm_t0) * 1000)
                        ttft_done = True
                    for sentence in splitter.feed(delta):
                        await tts_queue.put(("sentence", sentence))
                for sentence in splitter.flush():
                    await tts_queue.put(("sentence", sentence))
            finally:
                await tts_queue.put(None)

        worker_task = asyncio.create_task(_worker())
        producer_task = asyncio.create_task(_produce())

        # 主流程：按序发帧，句间停顿（A6）
        sent_idx = 0
        while True:
            frame = await frame_queue.get()
            if frame is None:
                break
            if sent_idx > 0 and self.sentence_gap_ms > 0:
                await asyncio.sleep(self.sentence_gap_ms / 1000.0)
            yield frame
            sent_idx += 1

        await producer_task
        await worker_task

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
