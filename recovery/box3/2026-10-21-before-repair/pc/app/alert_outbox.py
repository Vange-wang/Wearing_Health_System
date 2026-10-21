"""Persistent multi-channel health alert outbox.

BOX delivery is a lease: synthesis happens while an event is still pending,
successful synthesis creates a bounded lease, and only an explicit device ack
marks the BOX channel complete. The JSON file is replaced atomically so a
process restart can safely resume pending work.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

logger = logging.getLogger("voice-bridge.alert_outbox")


class AlertOutbox:
    VERSION = 1

    def __init__(
        self,
        state_file: str | Path,
        *,
        lease_seconds: float = 60,
        max_events: int = 256,
        retention_days: int = 30,
        time_fn: Callable[[], float] = time.time,
        uuid_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self.state_file = Path(state_file)
        self.lease_seconds = lease_seconds
        self.max_events = max_events
        self.retention_days = retention_days
        self._time = time_fn
        self._uuid_factory = uuid_factory
        self._lock = threading.RLock()
        self._events: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            document = json.loads(self.state_file.read_text(encoding="utf-8"))
            if document.get("version") != self.VERSION or not isinstance(
                document.get("events"), list
            ):
                raise ValueError("unsupported outbox document")
            self._events = [
                event
                for event in document["events"]
                if isinstance(event, dict) and isinstance(event.get("id"), str)
            ]
            changed = self._prune_locked(self._time())
            changed = self._release_expired_locked(self._time()) > 0 or changed
            if changed:
                self._save_locked()
            logger.info("告警出站箱载入：events=%d", len(self._events))
        except Exception:
            self._events = []
            logger.warning("告警出站箱状态损坏，忽略并等待下次原子写入", exc_info=True)

    def _save_locked(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        document = {"version": self.VERSION, "events": self._events}
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.state_file.name}.",
            suffix=".tmp",
            dir=self.state_file.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.state_file)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _prune_locked(self, now: float) -> bool:
        cutoff = now - self.retention_days * 86400
        before = len(self._events)
        self._events = [
            event for event in self._events if float(event.get("created_at", now)) >= cutoff
        ]
        self._events.sort(key=lambda event: float(event.get("created_at", 0)))
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]
        return len(self._events) != before

    def _find_locked(self, event_id: str) -> dict | None:
        return next((event for event in self._events if event.get("id") == event_id), None)

    def _release_expired_locked(self, now: float) -> int:
        released = 0
        for event in self._events:
            box = event.get("box", {})
            lease_until = box.get("lease_until")
            if (
                box.get("status") == "leased"
                and isinstance(lease_until, (int, float))
                and lease_until <= now
            ):
                box["status"] = "pending"
                box["lease_until"] = None
                event["updated_at"] = now
                released += 1
        return released

    def create_event(
        self,
        *,
        hr: float | None,
        spo2: float | None,
        quality: float,
        flags: int,
        seq: int | None,
    ) -> dict:
        now = self._time()
        event = {
            "id": self._uuid_factory(),
            "created_at": now,
            "updated_at": now,
            "snapshot": {
                "hr": hr,
                "spo2": spo2,
                "quality": quality,
                "flags": flags,
                "seq": seq,
            },
            "box": {
                "status": "pending",
                "lease_until": None,
                "acknowledged_at": None,
            },
            "wechat": {
                "status": "pending",
                "attempts": 0,
                "next_retry_at": now,
                "last_error": None,
                "succeeded_at": None,
            },
        }
        with self._lock:
            self._events.append(event)
            self._prune_locked(now)
            self._save_locked()
        logger.warning("健康告警事件生成 id=%s", event["id"])
        return copy.deepcopy(event)

    def get_event(self, event_id: str) -> dict | None:
        with self._lock:
            event = self._find_locked(event_id)
            return copy.deepcopy(event) if event is not None else None

    def peek_for_box(self) -> dict | None:
        now = self._time()
        with self._lock:
            if self._release_expired_locked(now):
                self._save_locked()
            event = next(
                (event for event in self._events if event.get("box", {}).get("status") == "pending"),
                None,
            )
            return copy.deepcopy(event) if event is not None else None

    def lease_for_box(self, event_id: str | None = None) -> dict | None:
        now = self._time()
        with self._lock:
            self._release_expired_locked(now)
            event = (
                self._find_locked(event_id)
                if event_id is not None
                else next(
                    (
                        candidate
                        for candidate in self._events
                        if candidate.get("box", {}).get("status") == "pending"
                    ),
                    None,
                )
            )
            if event is None or event.get("box", {}).get("status") != "pending":
                return None
            event["box"]["status"] = "leased"
            event["box"]["lease_until"] = now + self.lease_seconds
            event["updated_at"] = now
            self._save_locked()
            return copy.deepcopy(event)

    def acknowledge_box(self, event_id: str) -> bool:
        now = self._time()
        with self._lock:
            released = self._release_expired_locked(now)
            event = self._find_locked(event_id)
            if event is None:
                if released:
                    self._save_locked()
                return False
            status = event.get("box", {}).get("status")
            if status == "acknowledged":
                return True
            if status != "leased":
                if released:
                    self._save_locked()
                return False
            event["box"]["status"] = "acknowledged"
            event["box"]["lease_until"] = None
            event["box"]["acknowledged_at"] = now
            event["updated_at"] = now
            self._save_locked()
            return True

    def release_expired_leases(self) -> int:
        now = self._time()
        with self._lock:
            released = self._release_expired_locked(now)
            if released:
                self._save_locked()
            return released

    def pending_wechat(self) -> list[dict]:
        now = self._time()
        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._events
                if event.get("wechat", {}).get("status") == "pending"
                and float(event["wechat"].get("next_retry_at", 0)) <= now
            ]

    def mark_wechat_success(self, event_id: str) -> bool:
        now = self._time()
        with self._lock:
            event = self._find_locked(event_id)
            if event is None:
                return False
            if event["wechat"].get("status") == "succeeded":
                return True
            event["wechat"]["status"] = "succeeded"
            event["wechat"]["succeeded_at"] = now
            event["wechat"]["last_error"] = None
            event["updated_at"] = now
            self._save_locked()
            return True

    def mark_wechat_failure(
        self, event_id: str, *, category: str, next_retry_at: float
    ) -> bool:
        now = self._time()
        safe_category = "".join(
            character for character in category[:64] if character.isalnum() or character in "_-"
        ) or "send_error"
        with self._lock:
            event = self._find_locked(event_id)
            if event is None:
                return False
            event["wechat"]["status"] = "pending"
            event["wechat"]["attempts"] = int(event["wechat"].get("attempts", 0)) + 1
            event["wechat"]["next_retry_at"] = next_retry_at
            event["wechat"]["last_error"] = safe_category
            event["updated_at"] = now
            self._save_locked()
            return True
