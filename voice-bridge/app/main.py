"""FastAPI 入口与路由（Spec §5）。

接口：
- GET  /api/v1/health       → {"status","asr","tts"}
- POST /api/v1/voice/chat   → multipart audio(WAV 16k/16bit/mono ≤15s) → WAV bytes + X-Timing

打点：每步毫秒计时，X-Timing 响应头 + 每请求一条结构化日志（Spec §5）。
错误码：按 Spec §5 错误处理表完整实现。
"""
import json
import logging
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, Response

from .asr import ASRModelLoadError, create_asr
from .config import load_config
from .llm import LLMConfigError, create_llm
from .schemas import HealthResponse
from .tts import create_tts

logger = logging.getLogger("voice-bridge")

cfg = load_config()
logging.basicConfig(
    level=getattr(logging, str(cfg.log_level).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="voice-bridge", version="0.1")

asr = None
llm = None
tts = None
asr_load_error: str | None = None
llm_config_error: str | None = None


@app.on_event("startup")
def startup():
    """启动时预加载模型并报告状态（Spec §5 health）。"""
    global asr, llm, tts, asr_load_error, llm_config_error
    try:
        asr = create_asr(cfg)
    except ASRModelLoadError as e:
        asr_load_error = str(e)
        logger.error("ASR 预加载失败: %s", e)
    try:
        llm = create_llm(cfg)
    except LLMConfigError as e:
        llm_config_error = str(e)
        logger.error("LLM 配置失败: %s", e)
    try:
        tts = create_tts(cfg)
    except Exception as e:
        logger.error("TTS 初始化失败: %s", e)


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        asr="ready" if asr is not None else "unavailable",
        tts=tts.primary.name if tts is not None else "unavailable",
    )


@app.post("/api/v1/voice/chat")
async def voice_chat(audio: UploadFile = File(...)):
    t0 = time.perf_counter()

    if asr is None:
        return _err(503, "service_unavailable", asr_load_error or "ASR 未就绪")
    if llm is None:
        return _err(500, "config_error", llm_config_error or "LLM 配置缺失")
    if tts is None:
        return _err(503, "service_unavailable", "TTS 未就绪")

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

        # 3. TTS（edge 失败自动切 piper）
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


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def _err(status: int, error: str, detail: str | None = None):
    body = {"error": error}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body)
