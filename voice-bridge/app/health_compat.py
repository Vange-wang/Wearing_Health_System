"""Bound the legacy BOX JSON body without changing normal health decisions."""
import json

MAX_HEALTH_BYTES = 511


def _size(body):
    return len(json.dumps(body, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8"))


def compact_health(full):
    body = full.model_dump(exclude={"providers"})
    # Error detail has a separate, lossless endpoint. Keep booleans/timestamps.
    try:
        if _size(body) <= MAX_HEALTH_BYTES:
            return body
        if body["tts"].get("fallback_reason") is not None:
            body["tts"]["fallback_reason"] = "details_required"
        if _size(body) <= MAX_HEALTH_BYTES:
            return body
    except (ValueError, OverflowError, UnicodeError):
        pass
    # Unexpected unbounded provider names or non-finite metadata cannot produce
    # a valid legacy payload. Fail closed rather than truncate JSON or say READY.
    return {
        "status": "degraded", "asr": "unavailable",
        "tts": {"configured_primary": "unavailable", "active_engine": "unavailable",
                "fallback_reason": "health_payload_invalid_or_oversize",
                "last_probe_ok": False, "last_probe_ts": None},
        "vad": "disabled", "llm": "unavailable", "device_auth": "unavailable",
    }
