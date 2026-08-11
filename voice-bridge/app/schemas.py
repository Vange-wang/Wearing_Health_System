"""请求/响应模型（Spec §5）。"""
from typing import Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str  # "ok"
    asr: str     # "ready" | "unavailable"
    tts: str     # "edge" | "piper"


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
