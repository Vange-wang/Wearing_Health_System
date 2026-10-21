"""WeChat alert adapter with success-based quota accounting.

The adapter is synchronous and returns a sanitized result. It is called only
from the background outbox worker, never from the voice first-word path.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Callable

from .alert_outbox import AlertOutbox

logger = logging.getLogger("voice-bridge.wechat_alert")

HERMES_EXE = r"D:\miniconda\Scripts\hermes.exe"
PUSH_TIMEOUT_S = 30
RETRY_BASE_SECONDS = 30
RETRY_MAX_SECONDS = 3600
PROXY_ENV_KEYS = frozenset({"http_proxy", "https_proxy", "all_proxy"})


def _direct_connection_env() -> dict[str, str]:
    """Return a child environment that cannot route iLink through a proxy."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in PROXY_ENV_KEYS
    }


@dataclass(frozen=True)
class SendResult:
    success: bool
    category: str
    detail_safe: str


class WechatAlertPusher:
    """Hermes send adapter whose daily count advances only on return code 0."""

    def __init__(
        self,
        chat_id: str,
        daily_limit: int = 5,
        state_file: str | Path | None = None,
        enabled: bool = True,
        *,
        runner: Callable = subprocess.run,
        now_fn: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.chat_id = chat_id
        self.daily_limit = daily_limit
        self.state_file = Path(state_file) if state_file else None
        self.enabled = enabled and bool(chat_id)
        self._runner = runner
        self._now = now_fn
        self._lock = threading.Lock()
        self._today = None
        self._count = 0
        self._load_state()

    def _load_state(self) -> None:
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self._today = datetime.fromisoformat(data["date"]).date()
            self._count = int(data["count"])
            if self._count < 0:
                raise ValueError("negative count")
            self._rollover_locked()
            logger.info("微信成功计数载入：%s %d/%d", self._today, self._count, self.daily_limit)
        except Exception:
            self._today = None
            self._count = 0
            logger.warning("微信成功计数状态损坏，忽略")

    def _rollover_locked(self) -> None:
        today = self._now().date()
        if self._today != today:
            self._today = today
            self._count = 0

    def _save_state_locked(self) -> None:
        if self.state_file is None or self._today is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.state_file.name}.",
            suffix=".tmp",
            dir=self.state_file.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    {"date": self._today.isoformat(), "count": self._count},
                    stream,
                    separators=(",", ":"),
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.state_file)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @property
    def success_count(self) -> int:
        with self._lock:
            self._rollover_locked()
            return self._count

    def next_daily_reset_at(self) -> float:
        now = self._now()
        tomorrow = now.date() + timedelta(days=1)
        return datetime.combine(tomorrow, datetime_time.min).timestamp()

    @staticmethod
    def _build_message(hr: float | None, spo2: float | None) -> str:
        parts = []
        if hr is not None:
            parts.append(f"心率 {int(round(hr))}")
        if spo2 is not None:
            parts.append(f"血氧 {int(round(spo2))}%")
        detail = "、".join(parts) if parts else "检测数据"
        return f"健康提醒：最新检测异常（{detail}），建议关注一下。"

    def send(self, hr: float | None, spo2: float | None) -> SendResult:
        if not self.enabled:
            return SendResult(True, "disabled", "channel_disabled")
        message = self._build_message(hr, spo2)
        with self._lock:
            self._rollover_locked()
            if self._count >= self.daily_limit:
                return SendResult(False, "daily_limit", "deferred_to_next_day")
            try:
                result = self._runner(
                    [HERMES_EXE, "send", "-t", f"weixin:{self.chat_id}", message],
                    capture_output=True,
                    text=True,
                    timeout=PUSH_TIMEOUT_S,
                    env=_direct_connection_env(),
                )
            except subprocess.TimeoutExpired:
                return SendResult(False, "timeout", "send_timeout")
            except FileNotFoundError:
                return SendResult(False, "unavailable", "sender_not_found")
            except Exception as exc:
                return SendResult(False, "exception", type(exc).__name__[:64])
            if result.returncode != 0:
                return SendResult(False, "returncode", f"returncode_{result.returncode}")
            self._count += 1
            self._save_state_locked()
            logger.info("微信预警发送成功：今日 %d/%d", self._count, self.daily_limit)
            return SendResult(True, "sent", "ok")

    def push(self, hr: float | None, spo2: float | None) -> None:
        """Compatibility helper; new code uses the outbox worker."""
        threading.Thread(target=self.send, args=(hr, spo2), daemon=True).start()


def process_wechat_outbox_once(
    outbox: AlertOutbox,
    pusher: WechatAlertPusher,
    *,
    now_fn: Callable[[], float] = time.time,
) -> int:
    """Process every currently due WeChat channel once; return attempted count."""
    attempted = 0
    for event in outbox.pending_wechat():
        attempted += 1
        snapshot = event.get("snapshot", {})
        result = pusher.send(snapshot.get("hr"), snapshot.get("spo2"))
        if result.success:
            outbox.mark_wechat_success(event["id"])
            continue
        attempts = int(event.get("wechat", {}).get("attempts", 0))
        if result.category == "daily_limit":
            next_retry_at = pusher.next_daily_reset_at()
        else:
            delay = min(RETRY_BASE_SECONDS * (2**attempts), RETRY_MAX_SECONDS)
            next_retry_at = now_fn() + delay
        outbox.mark_wechat_failure(
            event["id"],
            category=result.category,
            next_retry_at=next_retry_at,
        )
        logger.warning(
            "微信告警待重试 id=%s category=%s next_retry_at=%.0f",
            event["id"],
            result.category,
            next_retry_at,
        )
    return attempted
