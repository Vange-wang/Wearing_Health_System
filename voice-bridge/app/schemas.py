"""请求/响应模型（Spec §5）。"""
from typing import Optional

from pydantic import BaseModel


class TTSHealth(BaseModel):
    """health 的 tts 嵌套对象（v0.2，Spec §5.1；v0.4 A5：edge 唯一）。"""

    configured_primary: str          # 固定 "edge"
    active_engine: str               # 恒 "edge"（A5 弃 piper）
    fallback_reason: Optional[str] = None  # 恒 None（无兜底）


class HealthResponse(BaseModel):
    status: str        # "ok"
    asr: str           # "ready" | "unavailable"
    tts: TTSHealth
    vad: str           # "enabled" | "disabled"
    llm: str           # v0.3：LLM 后端名（"hermes" | "unavailable"），如实上报


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
