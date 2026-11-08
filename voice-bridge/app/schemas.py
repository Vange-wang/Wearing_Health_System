"""请求/响应模型（Spec §5）。"""
from typing import Optional
from typing import Literal
import re

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
    providers: dict = Field(default_factory=dict)


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
    source_epoch: str | None = Field(default=None, strict=True, max_length=53)
    source_index: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)
    source_age_ms: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)

    @model_validator(mode="before")
    @classmethod
    def validate_source_presence(cls, data):
        if isinstance(data, dict):
            names = ("source_epoch", "source_index", "source_age_ms")
            if any(name in data for name in names):
                if not all(name in data and data[name] is not None for name in names):
                    raise ValueError("source fields must all be present")
                if type(data.get("seq")) is not int:
                    raise ValueError("enhanced source requires integer seq")
        return data

    @model_validator(mode="after")
    def validate_validity_flags(self):
        if self.source_epoch is not None:
            match = re.fullmatch(r"([0-9a-f]{32}):([0-9]+)", self.source_epoch, flags=re.ASCII)
            if match is None or len(match[2]) > 20 or int(match[2]) > 2**64 - 1:
                raise ValueError("invalid source_epoch")
            self.source_epoch = f"{match[1]}:{int(match[2])}"
            if self.seq is None or self.source_index & 255 != self.seq:
                raise ValueError("source_index must match seq")
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


class HealthDataStatus(BaseModel):
    module_ready: bool
    hr_available: bool
    spo2_available: bool
    source_age_verified: bool
    state: Literal["available", "no_data", "stale", "unavailable"]
