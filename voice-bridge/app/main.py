"""FastAPI 入口与路由（Spec §5 + v0.4 流式）。

接口：
- GET  /api/v1/health            → {"status","asr","tts":{...},"vad","llm"}
- POST /api/v1/voice/chat        → multipart audio(WAV 16k/16bit/mono ≤15s) → WAV bytes + X-Timing（v0.1 保留）
- POST /api/v1/voice/chat/stream → 长度前缀帧流（v0.2/v0.3 批式 ASR，Spec §5.3）
- POST /api/v1/voice/stream      → raw PCM chunked 流式上传 + 流式 ASR（v0.4 A2）
- POST /api/v1/knowledge/reload  → 知识库热重载

打点：每步毫秒计时，X-Timing 响应头 + 每请求一条结构化日志（Spec §5）。
错误码：按 Spec §5.4 错误处理表完整实现。
"""
import json
import logging
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .asr import ASRModelLoadError, create_asr, create_streaming_asr, read_wav_16k_mono
from .config import load_config
from .knowledge import KnowledgeBase
from .llm import LLMConfigError, LLMError, create_lightweight_llm, create_llm
from .pipeline import FrameTooLargeError, NoSpeechError, StreamingPipeline
from .router import Router
from .schemas import HealthResponse, TTSHealth
from .tts import TTSError, create_tts, probe_edge
from .vad import VADGate

logger = logging.getLogger("voice-bridge")

cfg = load_config()
logging.basicConfig(
    level=getattr(logging, str(cfg.log_level).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="voice-bridge", version="0.4")

asr = None
streaming_asr = None
llm = None
lightweight_llm = None
tts = None
vad = None
pipeline = None
knowledge = None
asr_load_error: str | None = None
streaming_asr_load_error: str | None = None
llm_config_error: str | None = None
tts_load_error: str | None = None


@app.on_event("startup")
async def startup():
    """启动时预加载模型、构造流水线并探测 edge 连通性（Spec §5.1 health）。"""
    global asr, streaming_asr, llm, lightweight_llm, tts, vad, pipeline, knowledge
    global asr_load_error, streaming_asr_load_error, llm_config_error, tts_load_error
    try:
        asr = create_asr(cfg)
    except ASRModelLoadError as e:
        asr_load_error = str(e)
        logger.error("ASR 预加载失败: %s", e)
    try:
        streaming_asr = create_streaming_asr(cfg)  # v0.4 A2 流式
    except ASRModelLoadError as e:
        streaming_asr_load_error = str(e)
        logger.error("流式 ASR 加载失败: %s", e)
    try:
        llm = create_llm(cfg)  # 慢路径 Hermes
    except LLMConfigError as e:
        llm_config_error = str(e)
        logger.error("LLM(Hermes) 配置失败: %s", e)
    try:
        lightweight_llm = create_lightweight_llm(cfg)  # 轻量通道 DeepSeek
    except LLMConfigError as e:
        logger.warning("轻量通道 DeepSeek 配置缺失: %s（轻量/知识库降级走慢路径）", e)
        lightweight_llm = None
    try:
        tts = create_tts(cfg)
        await probe_edge(tts, cfg.tts_edge_probe_timeout)
    except Exception as e:
        tts_load_error = str(e)
        logger.error("TTS 初始化失败: %s", e)

    vad = VADGate(
        enabled=cfg.vad_enabled,
        rms_threshold=cfg.vad_rms_threshold,
        min_speech_frames=cfg.vad_min_speech_frames,
    )

    knowledge = KnowledgeBase(cfg.rag_knowledge_dir)
    router = Router(tool_keywords=cfg.router_tool_keywords, skill_keywords=cfg.router_skill_keywords)

    if asr is not None and llm is not None and tts is not None:
        pipeline = StreamingPipeline(
            asr=asr,
            llm=llm,
            tts=tts,
            vad=vad,
            max_frame_bytes=cfg.pipeline_max_frame_bytes,
            sentence_max_chars=cfg.pipeline_sentence_max_chars,
            comfort_text=cfg.pipeline_comfort_text,
            sentence_gap_ms=cfg.pipeline_sentence_gap_ms,
            lightweight_llm=lightweight_llm,
            router=router,
            rag=knowledge,
            rag_top_k=cfg.rag_top_k,
            rag_score_threshold=cfg.rag_score_threshold,
        )


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    if tts is not None:
        tts_health = TTSHealth(**tts.health())
    else:
        tts_health = TTSHealth(
            configured_primary="edge",
            active_engine="unavailable",
            fallback_reason=None,
        )
    return HealthResponse(
        status="ok",
        asr="ready" if asr is not None else "unavailable",
        tts=tts_health,
        vad="enabled" if (vad is not None and vad.enabled) else "disabled",
        llm="hermes" if llm is not None else "unavailable",
    )


@app.post("/api/v1/knowledge/reload")
def knowledge_reload():
    """热重载知识库（长期 RAG，Spec §6.7）：重新扫描 knowledge/*.md 建索引。"""
    if knowledge is None:
        return _err(503, "service_unavailable", "知识库未初始化")
    count = knowledge.reload()
    return JSONResponse(status_code=200, content={"status": "ok", "count": count})


@app.post("/api/v1/voice/chat")
async def voice_chat(audio: UploadFile = File(...)):
    """v0.1 非流式，向后兼容，不改行为。"""
    t0 = time.perf_counter()

    if asr is None:
        return _err(503, "service_unavailable", asr_load_error or "ASR 未就绪")
    if llm is None:
        return _err(500, "config_error", llm_config_error or "LLM 配置缺失")
    if tts is None:
        return _err(503, "service_unavailable", tts_load_error or "TTS 未就绪")

    suffix = Path(audio.filename or "in.wav").suffix.lower()
    if suffix != ".wav":
        return _err(400, "bad_audio_format", f"仅支持 WAV，收到: {audio.filename}")

    data = await audio.read()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(data)
        wav_path = Path(tmp.name)

    timing = {"asr_ms": None, "llm_ms": None, "tts_ms": None, "total_ms": None}
    try:
        # 1. ASR
        t = time.perf_counter()
        try:
            text = asr.transcribe(wav_path)
        except ValueError as e:
            msg = str(e)
            if "audio_too_long" in msg:
                return _err(413, "audio_too_long", msg)
            return _err(400, "bad_audio_format", msg)
        except Exception as e:
            return _err(502, "upstream_error", f"ASR: {e}")
        timing["asr_ms"] = _ms(t)
        if not text:
            return _err(400, "no_speech", "ASR 未识别出有效语音")

        # 2. LLM（非流式）
        t = time.perf_counter()
        try:
            reply = llm.chat(text)
        except Exception as e:
            return _err(502, "upstream_error", f"LLM: {e}")
        timing["llm_ms"] = _ms(t)
        if not reply:
            return _err(502, "upstream_error", "LLM 返回空")

        # 3. TTS（edge 唯一，A5 弃 piper；失败 → 502）
        t = time.perf_counter()
        try:
            wav_bytes = await tts.synthesize(reply)
        except Exception as e:
            return _err(502, "upstream_error", f"TTS: {e}")
        timing["tts_ms"] = _ms(t)
    finally:
        wav_path.unlink(missing_ok=True)

    timing["total_ms"] = _ms(t0)
    logger.info(json.dumps({
        "ts": round(time.time(), 3),
        "asr_ms": timing["asr_ms"],
        "llm_ms": timing["llm_ms"],
        "tts_ms": timing["tts_ms"],
        "total_ms": timing["total_ms"],
        "asr_text_len": len(text),
        "tts_text_len": len(reply),
    }, ensure_ascii=False))

    return Response(
        content=wav_bytes,
        media_type="application/octet-stream",
        headers={"X-Timing": json.dumps(timing)},
    )


@app.post("/api/v1/voice/chat/stream")
async def voice_chat_stream(audio: UploadFile = File(...)):
    """v0.2 流式：长度前缀帧流（Spec §5.3）。

    open_ms = perf_counter(首字节 flush) - perf_counter(请求体完整接收)。
    首帧产出前，所有预期失败都以错误状态码返回。
    """
    if asr is None:
        return _err(503, "service_unavailable", asr_load_error or "ASR 未就绪")
    if llm is None:
        return _err(500, "config_error", llm_config_error or "LLM 配置缺失")
    if tts is None:
        return _err(503, "service_unavailable", tts_load_error or "TTS 未就绪")

    suffix = Path(audio.filename or "in.wav").suffix.lower()
    if suffix != ".wav":
        return _err(400, "bad_audio_format", f"仅支持 WAV，收到: {audio.filename}")

    if pipeline is None:
        return _err(503, "service_unavailable", "流水线未就绪")

    data = await audio.read()
    t0 = time.perf_counter()  # 请求体完整接收时刻 = open_ms 唯一起点（Spec §6.5）
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(data)
        wav_path = Path(tmp.name)

    # 格式校验 + 时长上限（读一次，VAD 用 samples，ASR 内部再读文件）
    try:
        samples = read_wav_16k_mono(wav_path, cfg.asr_sample_rate)
    except ValueError as e:
        msg = str(e)
        wav_path.unlink(missing_ok=True)
        if "audio_too_long" in msg:
            return _err(413, "audio_too_long", msg)
        return _err(400, "bad_audio_format", msg)

    # 预取首帧：VAD → ASR → LLM 首句 → 首句 TTS。此处任何失败都在响应头前返回。
    gen = pipeline.run(samples, wav_path)
    try:
        first_frame = await gen.__anext__()
    except NoSpeechError as e:
        wav_path.unlink(missing_ok=True)
        return _err(400, "no_speech", str(e))
    except (LLMError, TTSError) as e:
        wav_path.unlink(missing_ok=True)
        return _err(502, "upstream_error", str(e))
    except FrameTooLargeError as e:
        wav_path.unlink(missing_ok=True)
        return _err(502, "upstream_error", str(e))
    except Exception as e:
        wav_path.unlink(missing_ok=True)
        logger.exception("stream 首帧前未知异常")
        return _err(502, "upstream_error", str(e))

    # ASR 已完成，临时文件可释放
    wav_path.unlink(missing_ok=True)

    open_ms = _ms(t0)
    # v0.3 分段计量（Spec §4）：工具期如实上报、答案期卡线。
    # 首个正文 delta 前的一切（含工具调用）计入 tool_ms；answer_open_ms = open_ms - tool_ms。
    llm_stats = getattr(llm, "stats", {}) or {}
    _tool_seen = bool(llm_stats.get("tool_seen"))
    _first_content_ms = llm_stats.get("first_content_ms")
    if _tool_seen and _first_content_ms is not None:
        tool_ms = (pipeline.timing.get("asr_ms") or 0) + _first_content_ms
    else:
        tool_ms = 0
    timing = {
        "open_ms": open_ms,
        "asr_ms": pipeline.timing.get("asr_ms"),
        "llm_ttft_ms": pipeline.timing.get("llm_ttft_ms"),
        "tts_first_ms": pipeline.timing.get("tts_first_ms"),
        "tool_ms": tool_ms,
        "answer_open_ms": open_ms - tool_ms,
        "llm_backend": pipeline.timing.get("llm_backend"),
    }

    async def body():
        yield first_frame
        async for frame in gen:
            yield frame
        # 流结束：请求级结构化日志（全量 timing，不含语音正文）
        logger.info(json.dumps({
            "event": "request_done",
            "open_ms": open_ms,
            "tool_ms": tool_ms,
            "answer_open_ms": open_ms - tool_ms,
            "total_ms": _ms(t0),
            **{k: v for k, v in pipeline.timing.items() if v is not None},
        }, ensure_ascii=False))

    return StreamingResponse(
        body(),
        media_type="application/octet-stream",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Audio-Framing": "wav-length-prefixed",
            "X-Timing": json.dumps(timing),
        },
    )


@app.post("/api/v1/voice/stream")
async def voice_stream(request: Request):
    """v0.4 A2 流式：raw PCM chunked 上传 + 流式 ASR。

    请求体 = 16k/16bit/mono PCM 字节流（固件边录边发，HTTP chunked）；
    流结束（按键松开）→ final result → 路由 → LLM → TTS → 长度前缀帧流。
    """
    if streaming_asr is None:
        return _err(503, "service_unavailable", streaming_asr_load_error or "流式 ASR 未就绪")
    if pipeline is None:
        return _err(503, "service_unavailable", "流水线未就绪")

    t_req = time.perf_counter()
    stream = streaming_asr.create_stream()
    pcm_bytes = 0
    last_partial = ""
    leftover = b""  # 奇数字节缓存（TCP/chunked 分包可能在奇数边界切分 int16）

    async def _feed(chunk: bytes):
        nonlocal pcm_bytes, last_partial, leftover
        data = leftover + chunk
        leftover = b""
        if len(data) % 2 != 0:  # 奇数：缓存末字节，下个 chunk 拼接
            leftover = data[-1:]
            data = data[:-1]
        if not data:
            return
        pcm_bytes += len(data)
        # 16bit int16 → float32
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        streaming_asr.accept(stream, samples)
        partial = streaming_asr.partial(stream)
        if partial and partial != last_partial:
            last_partial = partial
            logger.info("ASR partial: %s", partial[:80])

    try:
        async for chunk in request.stream():
            await _feed(chunk)
    except Exception as e:
        logger.warning("PCM 流接收中断: %s", e)

    # 流结束 = 按键松开 → final result
    t_final = time.perf_counter()
    text = streaming_asr.final(stream)
    asr_ms = _ms(t_req)  # 收到请求 → final 的墙钟（含上传时间，流式识别近乎实时）
    final_decode_ms = _ms(t_final)
    logger.info("ASR final (%d chars, %d PCM bytes): %s", len(text), pcm_bytes, text[:80])
    if not text:
        return _err(400, "no_speech", "流式 ASR 未识别出有效语音")

    gen = pipeline.run_text(text)
    try:
        first_frame = await gen.__anext__()
    except NoSpeechError as e:
        return _err(400, "no_speech", str(e))
    except (LLMError, TTSError) as e:
        return _err(502, "upstream_error", str(e))
    except FrameTooLargeError as e:
        return _err(502, "upstream_error", str(e))
    except Exception as e:
        logger.exception("stream 首帧前未知异常")
        return _err(502, "upstream_error", str(e))

    open_ms = _ms(t_final)  # 按键松开 → 首帧（含路由+LLM+TTS）
    llm_stats = getattr(llm, "stats", {}) or {}
    _tool_seen = bool(llm_stats.get("tool_seen"))
    _first_content_ms = llm_stats.get("first_content_ms")
    tool_ms = _first_content_ms if (_tool_seen and _first_content_ms is not None) else 0
    timing = {
        "open_ms": open_ms,
        "asr_ms": asr_ms,
        "final_decode_ms": final_decode_ms,
        "llm_ttft_ms": pipeline.timing.get("llm_ttft_ms"),
        "tts_first_ms": pipeline.timing.get("tts_first_ms"),
        "tool_ms": tool_ms,
        "answer_open_ms": open_ms - tool_ms,
        "llm_backend": pipeline.timing.get("llm_backend"),
        "route": pipeline.timing.get("route"),
    }

    async def body():
        yield first_frame
        async for frame in gen:
            yield frame
        logger.info(json.dumps({
            "event": "request_done",
            "open_ms": open_ms,
            "asr_ms": asr_ms,
            "final_decode_ms": final_decode_ms,
            "total_ms": _ms(t_req),
            **{k: v for k, v in pipeline.timing.items() if v is not None},
        }, ensure_ascii=False))

    return StreamingResponse(
        body(),
        media_type="application/octet-stream",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Audio-Framing": "wav-length-prefixed",
            "X-Timing": json.dumps(timing),
        },
    )


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _err(status: int, error: str, detail: str | None = None):
    body = {"error": error}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body)
