"""FastAPI 入口与路由（Spec §5 + v0.4 流式）。

接口：
- GET  /api/v1/health            → {"status","asr","tts":{...},"vad","llm"}
- POST /api/v1/voice/chat        → multipart audio(WAV 16k/16bit/mono ≤15s) → WAV bytes + X-Timing（v0.1 保留）
- POST /api/v1/voice/chat/stream → 长度前缀帧流（v0.2/v0.3 批式 ASR，Spec §5.3）
- POST /api/v1/voice/stream      → raw PCM chunked 流式上传 + 流式 ASR（v0.4 A2）
- POST /api/v1/knowledge/reload  → 知识库热重载
- POST /api/v1/health/data       → BOX-3 上报健康数据（心率/血氧，BLE 立项 P3）
- GET  /api/v1/health/alert      → BOX-3 轮询预警（有预警返回 WAV 帧，BLE 立项 P4）

打点：每步毫秒计时，X-Timing 响应头 + 每请求一条结构化日志（Spec §5）。
错误码：按 Spec §5.4 错误处理表完整实现。
"""
import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from .asr import ASRModelLoadError, create_asr, create_streaming_asr, read_wav_16k_mono
from .config import load_config
from .health import HealthDataStore
from .wechat_alert import WechatAlertPusher
from .knowledge import KnowledgeBase
from .llm import LLMConfigError, LLMError, create_lightweight_llm, create_llm
from .memory import MemoryClient
from .pipeline import FrameTooLargeError, NoSpeechError, StreamingPipeline, encode_frame
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
health_store = None
asr_load_error: str | None = None
streaming_asr_load_error: str | None = None
llm_config_error: str | None = None
tts_load_error: str | None = None


@app.on_event("startup")
async def startup():
    """启动时预加载模型、构造流水线并探测 edge 连通性（Spec §5.1 health）。"""
    global asr, streaming_asr, llm, lightweight_llm, tts, vad, pipeline, knowledge, health_store
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
    # 单一记忆源（v2）：MemoryClient——注入本地读 USER.md/MEMORY.md，写删走 memory_server HTTP
    memory_client = MemoryClient(
        cfg.memory_api_url, cfg.user_profile_path, cfg.memory_file_path, cfg.memory_inject_budget
    )
    try:
        lightweight_llm = create_lightweight_llm(cfg, memory_store=memory_client)  # 轻量通道 DeepSeek
    except LLMConfigError as e:
        logger.warning("轻量通道 DeepSeek 配置缺失: %s（轻量/知识库降级走慢路径）", e)
        lightweight_llm = None
    if lightweight_llm is not None:
        # A7：后台预热 DeepSeek（消除首次按键冷启动 ~2s 尖峰）
        asyncio.create_task(asyncio.to_thread(lightweight_llm.warmup))
        # 方案1：周期心跳保温（保持 TLS 连接热，llm_ttft 稳定 ~500ms）
        lightweight_llm.start_heartbeat()
    try:
        tts = create_tts(cfg)
        await probe_edge(tts, cfg.tts_edge_probe_timeout)
    except Exception as e:
        tts_load_error = str(e)
        logger.error("TTS 初始化失败: %s", e)

    # 需求1：TTS 周期探活（每 5 分钟真实合成一次，更新 last_probe_ok/ts 供固件状态灯）
    async def _tts_probe_loop():
        while True:
            await asyncio.sleep(cfg.tts_probe_interval_s)
            if tts is not None:
                await tts.probe()
    if tts is not None:
        asyncio.create_task(_tts_probe_loop())

    vad = VADGate(
        enabled=cfg.vad_enabled,
        rms_threshold=cfg.vad_rms_threshold,
        min_speech_frames=cfg.vad_min_speech_frames,
    )

    knowledge = KnowledgeBase(cfg.rag_knowledge_dir)
    router = Router(
        tool_keywords=cfg.router_tool_keywords,
        skill_keywords=cfg.router_skill_keywords,
        data_keywords=cfg.router_data_keywords,
    )
    # BLE 健康数据缓存（P3 骨架）：接收 BOX-3 上报 + 阈值预警判定
    # P4：微信预警推送（update() 内触发，不依赖 BOX-3 轮询）
    wechat_pusher = WechatAlertPusher(
        chat_id=cfg.health_wechat_chat_id,
        daily_limit=cfg.health_wechat_daily_limit,
        state_file=str(Path(__file__).resolve().parent.parent / "logs" / "wechat_push_state.json"),
        enabled=cfg.health_wechat_push_enabled,
    )
    health_store = HealthDataStore(
        hr_high=cfg.health_hr_high,
        hr_low=cfg.health_hr_low,
        hr_low_night=cfg.health_hr_low_night,
        spo2_low=cfg.health_spo2_low,
        night_start=cfg.health_night_start,
        night_end=cfg.health_night_end,
        alert_consecutive=cfg.health_alert_consecutive,
        alert_cooldown_s=cfg.health_alert_cooldown_s,
        alert_cb=wechat_pusher.push,
    )

    # 慢路径安抚语预合成（query 池，随机轮换）。快路径 ack 已删除（首字延迟达标）。
    acknowledgements = {"query": []}
    ack_texts = cfg.pipeline_ack_query
    if tts is not None and ack_texts:
        async def _synth_one(text):
            try:
                return await tts.synthesize(text)
            except Exception as e:
                logger.warning("安抚语预合成失败(%s): %s", text, e)
                return None
        results = await asyncio.gather(*[_synth_one(t) for t in ack_texts])
        acknowledgements["query"] = [r for r in results if r is not None]
        logger.info("安抚语预合成完成：%d/%d 个", len(acknowledgements["query"]), len(ack_texts))

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
            acknowledgements=acknowledgements,
            health=health_store,
            data_stale_seconds=cfg.health_data_stale_seconds,
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


class HealthDataIn(BaseModel):
    """BOX-3 上报的健康数据（BLE 数据帧协议 §2 综合帧的 WiFi 侧形态）。"""

    hr: float | None = None       # 心率 BPM（None=无效）
    spo2: float | None = None     # 血氧 %（None=无效）
    seq: int | None = None        # 帧序号（丢帧检测）


@app.post("/api/v1/health/data")
def health_data(data: HealthDataIn):
    """BOX-3 上报健康数据 → 缓存 + 阈值判定（BLE 立项 P3）。"""
    if health_store is None:
        return _err(503, "service_unavailable", "健康数据模块未初始化")
    health_store.update(data.hr, data.spo2, data.seq)
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/api/v1/health/alert")
async def health_alert():
    """BOX-3 空闲轮询预警（BLE 立项 P4 方案 A）：有预警返回 WAV 帧，无则 204。"""
    if health_store is None or tts is None:
        return _err(503, "service_unavailable", "健康数据模块未初始化")
    alert = health_store.poll_alert()
    if alert is None:
        return Response(status_code=204)
    hr = alert.get("hr")
    spo2 = alert.get("spo2")
    parts = []
    if hr is not None:
        parts.append(f"心率 {int(round(hr))}")
    if spo2 is not None:
        parts.append(f"血氧 {int(round(spo2))}")
    text = "小V提醒您，" + "、".join(parts) + "，建议坐下来休息一下。"
    try:
        wav = await tts.synthesize(text)
        frame = encode_frame(wav, cfg.pipeline_max_frame_bytes)
    except Exception as e:
        logger.warning("预警播报 TTS 失败: %s", e)
        return _err(502, "upstream_error", f"TTS: {e}")
    return Response(
        content=frame,
        media_type="application/octet-stream",
        headers={"X-Audio-Framing": "wav-length-prefixed"},
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
        # 短语音/没听清：返回提示语音（单帧），而非 400 无反应
        try:
            wav = await tts.synthesize("没听清，请再说一次。")
            frame = encode_frame(wav, cfg.pipeline_max_frame_bytes)
        except Exception as e:
            logger.warning("短语音兜底 TTS 失败: %s", e)
            return _err(400, "no_speech", "流式 ASR 未识别出有效语音")
        return Response(
            content=frame,
            media_type="application/octet-stream",
            headers={"X-Audio-Framing": "wav-length-prefixed"},
        )

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
        logger.info("body: 已 yield first_frame，开始迭代 gen")
        try:
            async for frame in gen:
                logger.info("body: 收到帧 %dB，继续迭代", len(frame))
                yield frame
        except Exception as e:
            # 后续句 TTS/LLM 失败：已产出的帧照常播放，响应流优雅收尾（不中断连接）
            logger.error("后续帧生成失败（已播帧不受影响）: %s", e)
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
