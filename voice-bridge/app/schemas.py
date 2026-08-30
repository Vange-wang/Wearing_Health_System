"""请求/响应模型（Spec §5）。"""
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class TTSHealth(BaseModel):
    """health 的 tts 嵌套对象（v0.2，Spec §5.1；v0.4 A5：edge 唯一）。"""

    configured_primary: str          # 固定 "edge"
    active_engine: str               # 恒 "edge"（A5 弃 piper）
    fallback_reason: Optional[str] = None  # 恒 None（无兜底）
    last_probe_ok: Optional[bool] = None   # 需求1：真实合成探活结果（None=未探测）
    last_probe_ts: Optional[float] = None  # 需求1：最近探活时间戳


class HealthResponse(BaseModel):
    status: str        # "ok"
    asr: str           # "ready" | "unavailable"
    tts: TTSHealth
    vad: str           # "enabled" | "disabled"
    llm: str           # v0.3：LLM 后端名（"hermes" | "unavailable"），如实上报
    device_auth: str   # "ok" | "degraded" | "unavailable"，不含配置细节


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class HealthDataIn(BaseModel):
    """Validated BOX-3 health frame projected from the BLE combined frame."""

    hr: float | None = Field(default=None, ge=20, le=250)
    spo2: float | None = Field(default=None, ge=50, le=100)
    seq: int | None = Field(default=None, ge=0, le=255)
    flags: int | None = Field(default=None, ge=0, le=255)
    quality: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_validity_flags(self):
        if self.flags is None:
            self.flags = (0x01 if self.hr is not None else 0) | (
                0x02 if self.spo2 is not None else 0
            )
            return self
        if bool(self.flags & 0x01) != (self.hr is not None):
            raise ValueError("hr must match flags bit 0")
        if bool(self.flags & 0x02) != (self.spo2 is not None):
            raise ValueError("spo2 must match flags bit 1")
        return self
