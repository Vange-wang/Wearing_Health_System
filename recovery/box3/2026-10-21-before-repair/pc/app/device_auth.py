"""BOX-3 device-token authentication for protected device routes."""

from __future__ import annotations

import logging
import secrets
import threading
import time

from fastapi import FastAPI, HTTPException, Request


logger = logging.getLogger("voice-bridge.device_auth")
AUTH_HEADER = "X-Device-Token"
VALID_MODES = frozenset({"observe", "required"})
MISSING_WARNING_INTERVAL_S = 60.0


class DeviceAuthState:
    def __init__(self, token: str | None, mode: str):
        if mode not in VALID_MODES:
            raise ValueError("device auth mode must be observe or required")
        self.token = token
        self.mode = mode
        self._warning_lock = threading.Lock()
        self._last_missing_warning = float("-inf")

    @property
    def degraded(self) -> bool:
        return self.mode == "observe"

    def warn_missing_rate_limited(self) -> None:
        now = time.monotonic()
        with self._warning_lock:
            if now - self._last_missing_warning < MISSING_WARNING_INTERVAL_S:
                return
            self._last_missing_warning = now
        logger.warning("device token header missing while auth mode is observe")


def install_device_auth(app: FastAPI, *, token: str | None, mode: str) -> None:
    app.state.device_auth = DeviceAuthState(token=token, mode=mode)


def require_device_token(request: Request) -> None:
    state = getattr(request.app.state, "device_auth", None)
    if state is None or not state.token:
        raise HTTPException(status_code=503, detail="device authentication unavailable")

    values = request.headers.getlist(AUTH_HEADER)
    if not values or not values[0]:
        if state.mode == "observe":
            state.warn_missing_rate_limited()
            return
        raise HTTPException(status_code=401, detail="device token required")
    if len(values) != 1 or "," in values[0]:
        raise HTTPException(status_code=400, detail="ambiguous device token header")
    if not secrets.compare_digest(values[0], state.token):
        raise HTTPException(status_code=403, detail="device token rejected")
