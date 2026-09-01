"""流式流水线编排 + 长度前缀帧编码（Spec §5.3 / §6）。

Pipeline：VAD → ASR(批式) → LLM 流 → SentenceBuffer 分句 → 逐句 TTS → 长度前缀帧。
产出 `Iterator[bytes]`，每帧 = [4 字节大端长度] + [一句完整 WAV]。
解码接缝（A2）：契约是"PCM 16k/16bit/mono 进入 VAD/ASR"，M1 在 VAD 前插 opus→PCM 即可。
"""
import asyncio
import json
import logging
import random
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .splitter import SentenceBuffer
from .vad import VADGate
from .llm import LLMError, TOOL_SENTINEL
from .tts import TTSError
from .router import HERMES, LIGHTWEIGHT, RAG, DATA

logger = logging.getLogger("voice-bridge.pipeline")

SNAPSHOT_TTL_SECONDS = 600
CONTEXT_REPLY_MAX_CHARS = 500
SNAPSHOT_ROUTES = frozenset((LIGHTWEIGHT, RAG, HERMES, DATA))
REPLAY_NO_SNAPSHOT_TEXT = "刚才没有可以重复的内容哦，先跟我说说话吧。"
CONTEXT_NO_SNAPSHOT_TEXT = "我有点没跟上，你是指哪件事呀？"


def _timing_defaults() -> dict:
    return {
        "asr_ms": None,
        "llm_ttft_ms": None,
        "llm_total_ms": None,
        "tts_first_ms": None,
        "tts_total_ms": None,
        "sentence_count": 0,
        "chunk_count": 0,
        "llm_backend": "unknown",
        "tool_seen": False,
        "tool_ms": 0,
        "comfort_sent": False,
        "route": HERMES,
        "first_frame_ready_ms": None,
        "service_write_ms": None,
    }


@dataclass
class TimingRecord:
    """Mutable timing state owned by exactly one request."""

    _values: dict = field(default_factory=_timing_defaults)

    def __getitem__(self, key):
        return self._values[key]

    def __setitem__(self, key, value):
        self._values[key] = value

    def get(self, key, default=None):
        return self._values.get(key, default)

    def items(self):
        return self._values.items()

    def as_dict(self) -> dict:
        return self._values


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
        acknowledgements: dict | None = None,
        health=None,
        data_stale_seconds: float = 300,
        tts_workers: int = 8,
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
        # BLE 健康数据（P3 DATA 路由模板直答）：HealthDataStore + 新鲜度阈值
        self.health = health
        self.data_stale_seconds = float(data_stale_seconds)
        bind_health = getattr(self.lightweight_llm, "set_health_context_provider", None)
        if callable(bind_health):
            bind_health(self._build_lightweight_health_context)
        self.tts_workers = int(tts_workers)
        if not 1 <= self.tts_workers <= 16:
            raise ValueError("tts_workers must be between 1 and 16")
        # 慢路径安抚语池（预合成 WAV，query 池随机轮换）。快路径 ack 已删除（首字达标后不需要）。
        self.acknowledgements = acknowledgements or {}
        self._last_ack_idx: dict = {}
        # Backward-compatible snapshot for direct callers that do not supply a
        # request record. HTTP routes always pass their own TimingRecord.
        self.timing: dict = {}
        # ISSUE-0013：单设备进程内只保留最近一轮成功回复。锁内仅做 O(1)
        # 复制/替换，绝不覆盖 LLM、TTS、RAG 等 I/O。
        self._last_round_lock = threading.Lock()
        self._last_round: dict | None = None

    def _prepare_timing(self, timing: TimingRecord | None) -> TimingRecord:
        record = timing or TimingRecord()
        record["llm_backend"] = getattr(self.llm, "name", "unknown")
        if timing is None:
            self.timing = record.as_dict()
        return record

    def _read_last_round(self) -> dict | None:
        """读取未过期的最近成功轮次快照。"""
        now = time.monotonic()
        with self._last_round_lock:
            snapshot = self._last_round
            if snapshot is None:
                return None
            if now - snapshot["last_ts"] > SNAPSHOT_TTL_SECONDS:
                self._last_round = None
                return None
            return dict(snapshot)

    def _commit_last_round(self, user_text: str, reply_text: str, route: str) -> None:
        """在整轮帧成功产出后原子提交最近轮次。"""
        if not reply_text or route not in SNAPSHOT_ROUTES:
            return
        snapshot = {
            "last_user_text": user_text,
            "last_reply_text": reply_text,
            "last_route": route,
            "last_ts": time.monotonic(),
        }
        with self._last_round_lock:
            self._last_round = snapshot

    @staticmethod
    def _build_context_prompt(snapshot: dict, current_text: str) -> str:
        """构造仅含上一轮且长度受限的 CONTEXT 提示，不负责记录日志。"""
        return (
            f"【上一轮】用户：{snapshot['last_user_text']}\n"
            f"小V：{snapshot['last_reply_text'][:CONTEXT_REPLY_MAX_CHARS]}\n\n"
            f"【本轮】用户：{current_text}"
        )

    def _build_context_data_reply(self) -> str:
        """CONTEXT 延续 DATA：重报最新的全部新鲜字段，否则诚实降级。"""
        if self.health is None:
            return CONTEXT_NO_SNAPSHOT_TEXT
        hr, spo2 = self.health.get_fresh_values(self.data_stale_seconds)
        if hr is None and spo2 is None:
            return CONTEXT_NO_SNAPSHOT_TEXT
        return self._build_health_reply("")

    def _pick_ack(self, text: str) -> bytes | None:
        """慢路径安抚语：从 query 池随机轮换（避免连续重复）。

        快路径 ack 已删除（首字延迟达标后无需应声）；慢路径（Hermes 联网搜索）
        首字仍需 10~18s，故保留安抚语先行，避免干等。
        """
        pool = self.acknowledgements.get("query") or []
        if not pool:
            return None
        n = len(pool)
        idx = random.randrange(n)
        if n > 1 and idx == self._last_ack_idx.get("query", -1):
            idx = (idx + 1) % n
        self._last_ack_idx["query"] = idx
        return pool[idx]

    def _build_health_reply(self, text: str = "") -> str:
        """P3 DATA 模板直答（Spec §4.1）：根据最新健康数据构造回答，不经 LLM。

        - 问血压（未接入）→ 诚实口径（防误报血氧值）；
        - 显式问单字段 → 只报所问字段；双字段或无字段追问 → 报可用字段；
        - 有新鲜数据 → 报数值 + 正常/偏高/偏低判断；
        - 无数据或超新鲜度阈值 → 答「检测暂时中断」（Spec §6 第 7 条）。
        """
        if "血压" in text:
            return "血压功能还没有接入，心率和血氧可以查看。"
        if self.health is None:
            return "健康数据功能正在准备中，接入后就能帮你看了。"
        hr, spo2 = self.health.get_fresh_values(self.data_stale_seconds)
        if hr is None and spo2 is None:
            return "健康数据检测暂时中断了，请检查腕带是否佩戴好。"
        asks_hr = "心率" in text or "心跳" in text
        asks_spo2 = "血氧" in text
        has_explicit_field = asks_hr or asks_spo2
        include_hr = asks_hr or not has_explicit_field
        include_spo2 = asks_spo2 or not has_explicit_field
        parts = []
        if include_hr and hr is not None:
            hr_i = int(round(hr))
            h = time.localtime().tm_hour
            low = self.health.hr_low_night if (h >= self.health.night_start or h < self.health.night_end) else self.health.hr_low
            if hr_i > self.health.hr_high:
                parts.append(f"心率 {hr_i}，有点偏高")
            elif hr_i < low:
                parts.append(f"心率 {hr_i}，有点偏低")
            else:
                parts.append(f"心率 {hr_i}，正常")
        if include_spo2 and spo2 is not None:
            parts.append(f"血氧 {int(round(spo2))}")
        if not parts:
            return "健康数据检测暂时中断了，请检查腕带是否佩戴好。"
        return "您当前" + "，".join(parts) + "。"

    def _build_lightweight_health_context(self) -> str | None:
        """为健康语义回答提供逐字段新鲜的只读实测上下文。"""
        if self.health is None:
            return None
        latest = self.health.get_latest_fields()
        parts = []
        if (
            latest.hr is not None
            and latest.hr_age_s is not None
            and latest.hr_age_s <= self.data_stale_seconds
        ):
            parts.append(
                f"心率 {int(round(latest.hr))}（{int(round(latest.hr_age_s))}秒前）"
            )
        if (
            latest.spo2 is not None
            and latest.spo2_age_s is not None
            and latest.spo2_age_s <= self.data_stale_seconds
        ):
            parts.append(
                f"血氧 {int(round(latest.spo2))}（{int(round(latest.spo2_age_s))}秒前）"
            )
        if not parts:
            return None
        return "当前健康数据（仅可引用以下新鲜实测值）：" + "，".join(parts) + "。"

    async def run(
        self, samples: np.ndarray, wav_path: Path, timing: TimingRecord | None = None
    ):
        """批式路径（v0.2/v0.3 兼容）：VAD → 批式 ASR(SenseVoice) → 下游。"""
        timing = self._prepare_timing(timing)

        # 1. VAD
        if not self.vad.is_speech(samples):
            raise NoSpeechError("VAD 检测到静音/无效语音")

        # 2. ASR（批式）
        t = time.perf_counter()
        text = await asyncio.to_thread(self.asr.transcribe, wav_path)
        timing["asr_ms"] = round((time.perf_counter() - t) * 1000)
        if not text:
            raise NoSpeechError("ASR 未识别出有效语音")

        async for frame in self._stream_from_text(text, timing):
            yield frame

    async def run_text(self, text: str, timing: TimingRecord | None = None):
        """流式路径（v0.4 A2）：text 已由流式 ASR 给出，直接走下游（路由/LLM/TTS/帧）。"""
        timing = self._prepare_timing(timing)
        if not text:
            raise NoSpeechError("流式 ASR 未识别出有效语音")
        async for frame in self._stream_from_text(text, timing):
            yield frame

    async def _stream_from_text(self, text: str, timing: TimingRecord):
        """text → 路由（轻量/RAG/Hermes）→ LLM 流 → 分句 → TTS → 长度前缀帧。"""
        # ASR 近音词归一（血氧 → 血阳/学养/学样 同音误识别），路由前应用
        if self.router is not None:
            text = self.router.normalize_asr(text)
        followup_kind = (
            self.router.classify_followup(text) if self.router is not None else None
        )
        last_round = self._read_last_round() if followup_kind is not None else None

        # execution route 用于 timing 观测；response_route 决定沿用哪条现有响应链。
        # REPLAY 和无快照回退均为纯本地路径：不检索 RAG、不路由、不调用 LLM。
        local_followup = False
        context_followup = followup_kind == "context" and last_round is not None
        rag_results: list[dict] = []
        if followup_kind == "replay":
            route = "replay"
            response_route = "replay"
            selected_llm = None
            final_text = (
                last_round["last_reply_text"]
                if last_round is not None
                else REPLAY_NO_SNAPSHOT_TEXT
            )
            timing["llm_backend"] = "replay" if last_round is not None else "template"
            local_followup = True
        elif followup_kind == "context" and last_round is None:
            route = "context"
            response_route = "context"
            selected_llm = None
            final_text = CONTEXT_NO_SNAPSHOT_TEXT
            timing["llm_backend"] = "template"
            local_followup = True
        elif context_followup:
            route = "context"
            response_route = last_round["last_route"]
            if response_route == DATA:
                selected_llm = None
                final_text = self._build_context_data_reply()
                timing["llm_backend"] = "template"
                local_followup = True
            elif response_route == HERMES:
                selected_llm = self.llm
                final_text = self._build_context_prompt(last_round, text)
                timing["llm_backend"] = getattr(selected_llm, "name", "unknown")
            else:
                # LIGHTWEIGHT 与 RAG 都只调用轻量通道一次；RAG 不重新搜索、
                # 不再次包装知识库参考前缀。
                selected_llm = (
                    self.lightweight_llm
                    if self.lightweight_llm is not None
                    else self.llm
                )
                final_text = self._build_context_prompt(last_round, text)
                timing["llm_backend"] = getattr(selected_llm, "name", "unknown")
        else:
            # 路由判定 + RAG 检索（长期 RAG，Spec §3 A2 四步规则）
            if self.rag is not None:
                rag_results = self.rag.search(
                    text,
                    top_k=self.rag_top_k,
                    score_threshold=self.rag_score_threshold,
                )
            route = self.router.route(text, bool(rag_results)) if self.router else HERMES
            response_route = route

        timing["route"] = route

        if local_followup or context_followup:
            pass
        elif response_route == DATA:
            # P3 模板直答：不经 LLM，直接构造回答文本（确定性，防 LLM 读错数/编数，Spec §4.1）
            selected_llm = None
            final_text = self._build_health_reply(text)
            timing["llm_backend"] = "template"
        elif response_route == HERMES:
            selected_llm = self.llm
            final_text = text
            timing["llm_backend"] = getattr(selected_llm, "name", "unknown")
        else:
            selected_llm = self.lightweight_llm if self.lightweight_llm is not None else self.llm
            final_text = text
            if response_route == RAG and rag_results:
                ctx = "\n".join(
                    f"- {r['doc']['title']}: {r['doc']['text']}" for r in rag_results
                )
                final_text = f"【知识库参考，仅据以下内容回答】\n{ctx}\n\n用户问题：{text}"
            timing["llm_backend"] = getattr(selected_llm, "name", "unknown")

        # 方向1：快路径路由判定后立即预建 edge 连接（与 LLM 首句生成并行，省 ~0.65s 建连）。
        # 慢路径（Hermes）首句 >2s 才到，预连接会空闲恶化（C3 实测 2s 空闲净等待反而变慢），
        # 且已有安抚语先行，故慢路径不预连。
        preconn_state = None
        if response_route != HERMES and self.tts is not None and hasattr(self.tts, "open_preconnect"):
            preconn_state = {
                "task": asyncio.create_task(self.tts.open_preconnect()),
                "used": False,
                "disabled": False,
                "lock": asyncio.Lock(),
            }

        # LLM 流 → 分句 → 逐句 TTS → 帧
        splitter = SentenceBuffer(max_chars=self.sentence_max_chars)
        llm_t0 = time.perf_counter()
        ttft_done = False
        tts_total_ms = 0.0
        sentence_count = 0
        chunk_count = 0
        comfort_sent = False

        # 轻量/DeepSeek 首步失败（USER.md 读失败 / 网络不可达）→ 降级慢路径（A2 兜底）
        # DATA 模板直答：不走 LLM，模板文本直接作为单段「流」（后面分句+TTS 复用）
        if local_followup or response_route == DATA:
            delta_iter = iter([final_text])
        else:
            try:
                delta_iter = await asyncio.to_thread(selected_llm.stream_chat, final_text)
            except LLMError as e:
                if selected_llm is not self.llm:
                    logger.warning("轻量通道失败(%s)，降级慢路径 Hermes", e)
                    if followup_kind is None:
                        timing["route"] = HERMES
                    timing["llm_backend"] = getattr(self.llm, "name", "unknown")
                    selected_llm = self.llm  # 需求3：更新实际后端，避免误判提取
                    fallback_text = final_text if context_followup else text
                    delta_iter = await asyncio.to_thread(
                        self.llm.stream_chat, fallback_text
                    )
                    # 方向1：降级慢路径 → 禁用预连接（慢路径不预连，收尾统一关闭）
                    if preconn_state is not None:
                        preconn_state["disabled"] = True
                else:
                    raise

        # 预合成流水线（并发 worker + 序号重排）：
        # produce(LLM 分句) → tts_queue → N worker 并发 TTS → frame_queue → 按序发帧
        # 并发合成：edge 每句独立连接可并发（8 句 2.2s 实测稳定）；序号重排保证句子顺序
        worker_count = self.tts_workers
        tts_queue: asyncio.Queue = asyncio.Queue()
        frame_queue: asyncio.Queue = asyncio.Queue()
        tts_first_recorded = False
        comfort_queued = False
        tts_wall_t0 = None
        total_sentences = [0]
        delivery_failed = [False]
        assistant_parts: list[str] = []  # 需求3：收集 LLM 完整回复（回复完成后提取记忆）

        async def _claim_preconn():
            """方向1：原子 claim 预连接（仅首个正文句能拿到），失败/已被用/已禁用返回 None。"""
            if preconn_state is None or preconn_state["disabled"]:
                return None
            async with preconn_state["lock"]:
                if preconn_state["used"]:
                    return None
                preconn_state["used"] = True
            try:
                return await preconn_state["task"]
            except Exception:
                return None

        async def _drain_stream(seg_iter, seq, kind, t0):
            """流式产帧到 frame_queue。返回 (seg_i, last_seg, emitted_any, completed)。

            emitted_any=False 表示首段未产出即失败，调用方可回退重合成。
            """
            nonlocal tts_first_recorded
            seg_i = 0
            last_seg = None
            emitted_any = False
            completed = True
            try:
                async for seg_wav in seg_iter:
                    if not tts_first_recorded:
                        timing["tts_first_ms"] = round((time.perf_counter() - t0) * 1000)
                        tts_first_recorded = True
                    emitted_any = True
                    if last_seg is not None:
                        await frame_queue.put(((seq, seg_i), kind, last_seg, False))
                        seg_i += 1
                    last_seg = seg_wav
            except TTSError as e:
                completed = False
                logger.error("TTS 流式合成失败: %s", e)
            return seg_i, last_seg, emitted_any, completed

        async def _worker():
            nonlocal tts_first_recorded, tts_wall_t0
            try:
                while True:
                    item = await tts_queue.get()
                    if item is None:
                        logger.info("worker: 收到结束哨兵，退出")
                        break
                    seq, kind, sentence = item
                    logger.info("worker: 取到任务 seq=%s kind=%s 句子=%r", seq, kind, (sentence or '')[:20])
                    try:
                        t0 = time.perf_counter()
                        if tts_wall_t0 is None:
                            tts_wall_t0 = t0
                        preconn = None
                        if kind == "sentence" and preconn_state is not None:
                            preconn = await _claim_preconn()
                        if hasattr(self.tts, "stream_synthesize"):
                            logger.info("worker: 开始 TTS 合成 seq=%s kind=%s", seq, kind)
                            if preconn is not None:
                                seg_i, last_seg, emitted, completed = await _drain_stream(
                                    preconn.stream_synthesize(sentence), seq, kind, t0
                                )
                                await preconn.close()
                                if not emitted:
                                    logger.warning("预连接首句失败，回退用时建连重合成")
                                    seg_i, last_seg, _, completed = await _drain_stream(
                                        self.tts.stream_synthesize(sentence), seq, kind, t0
                                    )
                                elif not completed:
                                    delivery_failed[0] = True
                            else:
                                seg_i, last_seg, _, completed = await _drain_stream(
                                    self.tts.stream_synthesize(sentence), seq, kind, t0
                                )
                            if not completed:
                                delivery_failed[0] = True
                            logger.info("worker: TTS 合成完成 seq=%s seg_i=%s", seq, seg_i)
                            if last_seg is not None:
                                await frame_queue.put(((seq, seg_i), kind, last_seg, True))
                            else:
                                delivery_failed[0] = True
                                await frame_queue.put(((seq, 0), kind, None, True))
                        else:
                            wav = await self.tts.synthesize(sentence)
                            dur_ms = (time.perf_counter() - t0) * 1000
                            if not tts_first_recorded:
                                timing["tts_first_ms"] = round(dur_ms)
                                tts_first_recorded = True
                            await frame_queue.put(((seq, 0), kind, wav, True))
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        # Always complete the claimed sequence so the reorder
                        # loop can advance instead of waiting forever.
                        delivery_failed[0] = True
                        logger.exception("并发合成 TTS 异常（跳过该句）: %s", e)
                        await frame_queue.put(((seq, 0), kind, None, True))
            finally:
                await frame_queue.put((None, "worker_done", None, None))

        async def _produce():
            nonlocal ttft_done, comfort_queued, total_sentences
            seq = 0
            it = iter(delta_iter)
            sentinel = object()

            # ISSUE-0001 修复：慢路径（Hermes）路由判定后立即发安抚语，不等首 token。
            # 慢路径由 tool_keywords 触发 → _pick_ack 命中 query 池（「稍等，我帮你查一下」）。
            if response_route == HERMES:
                ack_wav = self._pick_ack(text)
                if ack_wav is not None:
                    await frame_queue.put(((seq, 0), "comfort", ack_wav, True))
                    seq += 1
                    comfort_queued = True

            def _next_delta():
                try:
                    return next(it)
                except StopIteration:
                    return sentinel

            try:
                while True:
                    logger.info("produce: 等下一个 delta（阻塞读 LLM 流）...")
                    delta = await asyncio.to_thread(_next_delta)
                    if delta is sentinel:
                        logger.info("produce: 收到 sentinel，流结束")
                        break
                    if delta is TOOL_SENTINEL:
                        logger.info("produce: 收到 TOOL_SENTINEL（工具调用），comfort_queued=%s", comfort_queued)
                        # 慢路径哨兵（工具调用）→ 安抚语优先合成（A5）
                        if not comfort_queued:
                            await tts_queue.put((seq, "comfort", self.comfort_text))
                            seq += 1
                            comfort_queued = True
                        continue
                    logger.info("produce: 收到 content 片段 %r", delta[:20])
                    assistant_parts.append(delta)  # 需求3：累积回复全文，回复完成后提取记忆
                    if not ttft_done:
                        timing["llm_ttft_ms"] = round((time.perf_counter() - llm_t0) * 1000)
                        ttft_done = True
                    for sentence in splitter.feed(delta):
                        await tts_queue.put((seq, "sentence", sentence))
                        seq += 1
                for sentence in splitter.flush():
                    await tts_queue.put((seq, "sentence", sentence))
                    seq += 1
            finally:
                # This is the LLM/template stream completion boundary. It must
                # not include TTS workers, frame reordering, or sentence gaps.
                timing["llm_total_ms"] = round((time.perf_counter() - llm_t0) * 1000)
                total_sentences[0] = seq  # 总句数（含安抚语），供主流程判断结束
                for _ in range(worker_count):
                    await tts_queue.put(None)
                await frame_queue.put((None, "producer_done", None, None))

        workers = [asyncio.create_task(_worker()) for _ in range(worker_count)]
        producer_task = asyncio.create_task(_produce())

        # 主流程：序号重排 + 句间停顿（A6，仅句边界加停顿，句内多帧连续）
        next_sentence_seq = 0
        next_seg = 0
        pending: dict = {}
        total_frames = 0
        prev_is_end = True  # 首帧前不加停顿
        producer_done = False
        workers_done = 0
        while True:
            item = await frame_queue.get()
            if item[0] is None:
                if item[1] == "producer_done":
                    producer_done = True
                elif item[1] == "worker_done":
                    workers_done += 1
                if (
                    producer_done
                    and workers_done >= worker_count
                    and next_sentence_seq >= total_sentences[0]
                ):
                    break
                continue
            key, kind, wav, is_end = item
            seq_i, seg_i = key
            logger.info("main: 收到帧 key=%s kind=%s is_end=%s next_sentence_seq=%s", key, kind, is_end, next_sentence_seq)
            pending[key] = (kind, wav, is_end)
            while (next_sentence_seq, next_seg) in pending:
                kind, wav, is_end = pending.pop((next_sentence_seq, next_seg))
                if wav is not None:
                    if kind == "comfort":
                        if next_seg == 0:
                            comfort_sent = True
                            timing["comfort_sent"] = True
                    else:
                        if next_seg == 0:
                            sentence_count += 1
                    chunk_count += 1
                    # 句间停顿：仅上一帧是句尾时（句内多帧不打断）
                    if total_frames > 0 and self.sentence_gap_ms > 0 and prev_is_end:
                        await asyncio.sleep(self.sentence_gap_ms / 1000.0)
                    yield encode_frame(wav, self.max_frame_bytes)
                    total_frames += 1
                    prev_is_end = is_end
                if is_end:
                    next_sentence_seq += 1
                    next_seg = 0
                else:
                    next_seg += 1
            if (
                producer_done
                and workers_done >= worker_count
                and next_sentence_seq >= total_sentences[0]
            ):
                logger.info("main: done, next_sentence_seq=%s total=%s", next_sentence_seq, total_sentences[0])
                break

        await producer_task
        for w in workers:
            await w
        reply_text = "".join(assistant_parts).strip()
        # 需求3（改造）：回复完成后统一触发记忆提取（全自动，每轮必做，不依赖流正常结束）。
        # 覆盖 lightweight/rag 路由（DeepSeek 提取）；hermes 慢路径 Hermes 自带 persistent
        # memory（豁免），DATA 模板直答无用户新信息（豁免）。
        if selected_llm is not None and selected_llm is self.lightweight_llm and hasattr(selected_llm, "extract_memory_async"):
            if reply_text:
                selected_llm.extract_memory_async(text, reply_text)
        # 方向1：预连接未被消费则关闭（降级慢路径 / 预连接失败 / 无正文句场景，避免连接泄漏）
        if preconn_state is not None:
            pre = None
            try:
                pre = await preconn_state["task"]
            except Exception:
                pre = None
            if pre is not None and not preconn_state["used"]:
                await pre.close()
        if tts_wall_t0 is not None:
            tts_total_ms = (time.perf_counter() - tts_wall_t0) * 1000

        timing["tts_total_ms"] = round(tts_total_ms)
        timing["sentence_count"] = sentence_count
        timing["chunk_count"] = chunk_count
        timing["comfort_sent"] = comfort_sent
        # 分段计量：工具期 ≈ 请求→首个正文 delta（工具期间无正文）
        stats = getattr(selected_llm, "stats", {}) or {}
        tool_seen = bool(stats.get("tool_seen"))
        first_content_ms = stats.get("first_content_ms")
        timing["tool_seen"] = tool_seen
        if tool_seen and first_content_ms is not None:
            timing["tool_ms"] = (timing["asr_ms"] or 0) + first_content_ms
        else:
            timing["tool_ms"] = 0
        # 只有普通轮次在所有响应帧成功产出并完成收尾后覆盖快照。
        # REPLAY/无快照回退不创建、不刷新快照。
        snapshot_commit_allowed = not delivery_failed[0] and total_frames > 0
        if followup_kind is None and snapshot_commit_allowed:
            self._commit_last_round(text, reply_text, timing["route"])
        elif context_followup and snapshot_commit_allowed:
            self._commit_last_round(
                text, reply_text, last_round["last_route"]
            )
        logger.info(json.dumps({
            "event": "stream_done",
            **{k: v for k, v in timing.items() if v is not None},
        }, ensure_ascii=False))
