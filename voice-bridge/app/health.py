"""健康数据缓存 + 阈值预警判定（BLE 立项 Spec §5/§6）。

- P3 骨架：数据接收缓存 + 新鲜度判断（供 DATA 路由模板直答）。
- P4 预警：连续 N 次超阈值 + 冷却（供 /health/alert 轮询）。
- P4 微信推送：连续次数恰好达到阈值的瞬间触发 alert_cb（不依赖 BOX-3 轮询，
  任务单 2026-08-23-P4 任务 A 要求）；日上限在推送层（wechat_alert.py）做。

单 BOX-3 设备场景：内存缓存即可（多设备时需按来源分桶）。
"""
import logging
import threading
import time
import re
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("voice-bridge.health")


class HealthIdentityError(ValueError):
    """A conflicting/replayed frame cannot mutate accepted physiology."""


@dataclass(frozen=True)
class HealthSnapshot:
    """Latest accepted values and independent monotonic ages."""

    hr: float | None
    spo2: float | None
    hr_age_s: float | None
    spo2_age_s: float | None
    link_age_s: float | None
    seq: int | None
    flags: int | None
    quality: float | None


class HealthDataStore:
    """最新健康数据内存缓存 + 阈值预警状态机。"""

    def __init__(
        self,
        hr_high: float = 100,
        hr_low: float = 50,
        hr_low_night: float = 45,
        spo2_low: float = 95,
        night_start: int = 23,
        night_end: int = 6,
        alert_consecutive: int = 3,
        alert_cooldown_s: float = 600,
        alert_cb: Callable[[dict], None] | None = None,
        *,
        min_quality: float = 0.5,
        alert_max_age_s: float = 1800,
        monotonic: Callable[[], float] = time.monotonic,
        data_stale_seconds: float = 300,
    ):
        self.hr_high = hr_high
        self.hr_low = hr_low
        self.hr_low_night = hr_low_night
        self.spo2_low = spo2_low
        self.night_start = night_start
        self.night_end = night_end
        self.alert_consecutive = alert_consecutive
        self.alert_cooldown_s = alert_cooldown_s
        self.min_quality = min_quality
        self.alert_max_age_s = alert_max_age_s
        self._alert_cb = alert_cb   # 事件出站箱回调，锁外调用
        self._monotonic = monotonic
        self.data_stale_seconds = data_stale_seconds

        self._lock = threading.Lock()
        self._hr: float | None = None
        self._spo2: float | None = None
        self._hr_ts: float | None = None
        self._spo2_ts: float | None = None
        self._link_ts: float | None = None
        self._seq: int | None = None
        self._flags: int | None = None
        self._quality: float | None = None

        # 预警状态：连续超阈值计数 + episode/cooldown 事件生成
        self._over_count = 0
        self._episode_active = False
        self._last_event_ts: float | None = None
        self._legacy_pending: dict | None = None
        self._epoch = None
        self._source_index = None
        self._retired_boots = set()
        self._business_frame = None
        self._independent_ts = None
        self._hr_source_verified = self._spo2_source_verified = False
        self._epoch_cooldown_guard = False

    def _identity_locked(self, seq, business, source_epoch, source_index, now):
        """Compare and commit the single authenticated BOX frontier in O(1)."""
        if source_epoch is None:
            if self._epoch is not None:
                raise HealthIdentityError("legacy_after_enhanced")
            confirm = seq is not None
            expired = self._independent_ts is not None and now - self._independent_ts > self.data_stale_seconds
            if seq is not None and self._seq is not None:
                difference = (seq - self._seq) & 255
                if not expired and difference == 0:
                    if business != self._business_frame:
                        raise HealthIdentityError("identity_conflict")
                    return "duplicate", False
                if expired or difference >= 128:
                    confirm = False
                    self._over_count = 0
                    self._episode_active = False
            elif expired:
                confirm = False
                self._over_count = 0
                self._episode_active = False
            self._business_frame = business
            self._independent_ts = now
            return "ok", confirm
        boot, generation = source_epoch.split(":")
        epoch = (boot, int(generation))
        if epoch != self._epoch:
            if self._epoch is not None:
                old_boot, old_generation = self._epoch
                if boot == old_boot:
                    if epoch[1] <= old_generation:
                        raise HealthIdentityError("stale_identity")
                else:
                    if boot in self._retired_boots:
                        raise HealthIdentityError("stale_identity")
                    if len(self._retired_boots) >= 256:
                        raise HealthIdentityError("identity_capacity")
                    self._retired_boots.add(old_boot)
            # All rejection checks precede accepted epoch/alert state commits.
            if self._epoch is not None and self._last_event_ts is not None:
                self._epoch_cooldown_guard = True
            self._epoch = epoch
            self._source_index = None
            self._business_frame = None
            self._hr = self._spo2 = self._hr_ts = self._spo2_ts = None
            self._hr_source_verified = self._spo2_source_verified = False
            self._over_count = 0
            self._episode_active = False
            # Keep last_event_ts/outbox/pending events: reconnect is not a way
            # around the pre-existing event cooldown.
        if self._source_index is not None:
            if source_index < self._source_index:
                raise HealthIdentityError("stale_identity")
            if source_index == self._source_index:
                if business != self._business_frame:
                    raise HealthIdentityError("identity_conflict")
                return "duplicate", False
        self._source_index, self._business_frame = source_index, business
        self._independent_ts = now
        return "ok", True

    def update(
        self,
        hr: float | None,
        spo2: float | None,
        seq: int | None = None,
        flags: int | None = None,
        quality: float = 1.0,
        *, source_epoch: str | None = None, source_index: int | None = None,
        source_age_ms: int | None = None,
    ) -> str:
        """接收一帧数据（hr BPM / spo2 %，None 表示该字段无效）。

        None 字段保留上一有效值，但不会刷新该字段时间戳。bit0/bit1 是
        HR/SpO2 有效位，bit2 是运动伪影。伪影或低质量帧只刷新链路状态，
        不刷新生理字段，也不中累计连续异常。
        """
        now = self._monotonic()
        if flags is None:
            flags = (0x01 if hr is not None else 0) | (0x02 if spo2 is not None else 0)
        enhanced = source_epoch is not None
        provided = (source_epoch is not None, source_index is not None, source_age_ms is not None)
        if any(provided) and not all(provided):
            raise HealthIdentityError("invalid_identity")
        if enhanced:
            match = re.fullmatch(r"([0-9a-f]{32}):([0-9]{1,20})", source_epoch, flags=re.ASCII) if isinstance(source_epoch, str) else None
            if (match is None or int(match[2]) > 2**64 - 1
                    or type(source_index) is not int or not 0 <= source_index <= 2**63 - 1
                    or type(source_age_ms) is not int or not 0 <= source_age_ms <= 2**63 - 1
                    or type(seq) is not int or source_index & 255 != seq):
                raise HealthIdentityError("invalid_identity")
        source_age = source_age_ms / 1000 if enhanced else 0
        source_fresh = source_age <= self.data_stale_seconds
        quality_ok = source_fresh and 0.0 <= quality <= 1.0 and quality >= self.min_quality
        artifact = bool(flags & 0x04)
        hr_valid = quality_ok and not artifact and bool(flags & 0x01) and hr is not None
        spo2_valid = quality_ok and not artifact and bool(flags & 0x02) and spo2 is not None
        accepted_hr = hr if hr_valid else None
        accepted_spo2 = spo2 if spo2_valid else None
        fire: dict | None = None
        with self._lock:
            status, confirm = self._identity_locked(seq, (hr, spo2, seq, flags, quality),
                                                    source_epoch, source_index, now)
            self._link_ts = now
            if status == "duplicate":
                return status
            self._seq = seq
            self._flags = flags
            self._quality = quality
            if hr_valid:
                self._hr = hr
                self._hr_ts = now - source_age
                self._hr_source_verified = enhanced
            if spo2_valid:
                self._spo2 = spo2
                self._spo2_ts = now - source_age
                self._spo2_source_verified = enhanced
            # 只判定本帧通过质量门的字段；陈旧合并值不得维持异常计数。
            if confirm and (hr_valid or spo2_valid) and self._is_over(accepted_hr, accepted_spo2):
                self._over_count += 1
            else:
                self._over_count = 0
                self._episode_active = False
            # 达阈值开启 episode；异常持续时每过 cooldown 生成一个新事件。
            if (
                self._over_count >= self.alert_consecutive
                and (
                    (not self._episode_active and not self._epoch_cooldown_guard)
                    or self._last_event_ts is None
                    or now - self._last_event_ts >= self.alert_cooldown_s
                )
            ):
                fresh_hr, fresh_spo2 = self._fresh_values_locked(now, self.alert_max_age_s)
                if fresh_hr is not None or fresh_spo2 is not None:
                    fire = {
                        "hr": fresh_hr,
                        "spo2": fresh_spo2,
                        "quality": quality,
                        "flags": flags,
                        "seq": seq,
                    }
                    self._episode_active = True
                    self._epoch_cooldown_guard = False
                    self._last_event_ts = now
                    self._legacy_pending = dict(fire)
            over_count = self._over_count
        logger.debug(
            "health update hr=%s spo2=%s seq=%s flags=0x%02x quality=%.2f over_count=%d",
            hr,
            spo2,
            seq,
            flags,
            quality,
            over_count,
        )
        if fire is not None:
            try:
                if self._alert_cb is not None:
                    self._alert_cb(fire)
            except Exception:
                logger.exception("预警事件回调异常")
        return status

    def data_status(self, seconds: float) -> dict:
        """Read existing field freshness under the same lock, without mutation."""
        now = self._monotonic()
        with self._lock:
            hr, spo2 = self._fresh_values_locked(now, seconds)
            available = hr is not None or spo2 is not None
            verified = available and (hr is None or self._hr_source_verified) and (spo2 is None or self._spo2_source_verified)
            state = "available" if available else "stale" if self._hr_ts is not None or self._spo2_ts is not None else "no_data"
            return dict(module_ready=True, hr_available=hr is not None, spo2_available=spo2 is not None,
                        source_age_verified=bool(verified), state=state)

    def get_latest(self) -> tuple[float | None, float | None, float | None]:
        """兼容接口：返回值与最近有效字段年龄；新代码应使用 get_latest_fields。"""
        latest = self.get_latest_fields()
        ages = [
            age
            for value, age in ((latest.hr, latest.hr_age_s), (latest.spo2, latest.spo2_age_s))
            if value is not None and age is not None
        ]
        age = min(ages) if ages else None
        return latest.hr, latest.spo2, age

    def get_latest_fields(self) -> HealthSnapshot:
        """返回每个健康字段和链路各自的单调时钟年龄。"""
        now = self._monotonic()
        with self._lock:
            return HealthSnapshot(
                hr=self._hr,
                spo2=self._spo2,
                hr_age_s=None if self._hr_ts is None else now - self._hr_ts,
                spo2_age_s=None if self._spo2_ts is None else now - self._spo2_ts,
                link_age_s=None if self._link_ts is None else now - self._link_ts,
                seq=self._seq,
                flags=self._flags,
                quality=self._quality,
            )

    def get_fresh_values(self, seconds: float) -> tuple[float | None, float | None]:
        """Return only fields whose own timestamp is within ``seconds``."""
        latest = self.get_latest_fields()
        hr = latest.hr if latest.hr_age_s is not None and latest.hr_age_s <= seconds else None
        spo2 = (
            latest.spo2
            if latest.spo2_age_s is not None and latest.spo2_age_s <= seconds
            else None
        )
        return hr, spo2

    def has_data_within(self, seconds: float) -> bool:
        """最近 seconds 秒内是否有有效数据（新鲜度判断）。"""
        hr, spo2 = self.get_fresh_values(seconds)
        return hr is not None or spo2 is not None

    def _fresh_values_locked(
        self, now: float, seconds: float
    ) -> tuple[float | None, float | None]:
        hr = self._hr if self._hr_ts is not None and now - self._hr_ts <= seconds else None
        spo2 = (
            self._spo2
            if self._spo2_ts is not None and now - self._spo2_ts <= seconds
            else None
        )
        return hr, spo2

    def _hr_low_now(self) -> float:
        """当前时段的血氧下限阈值（夜间下调，防老人睡眠心动过缓误报）。"""
        h = time.localtime().tm_hour
        if h >= self.night_start or h < self.night_end:
            return self.hr_low_night
        return self.hr_low

    def _is_over(self, hr: float | None, spo2: float | None) -> bool:
        """单次采样是否超阈值（任一字段超限即判超）。"""
        if hr is not None:
            if hr > self.hr_high or hr < self._hr_low_now():
                return True
        if spo2 is not None and spo2 < self.spo2_low:
            return True
        return False

    def poll_alert(self) -> dict | None:
        """Legacy in-memory consumer; new BOX delivery uses AlertOutbox leases."""
        now = self._monotonic()
        with self._lock:
            if self._legacy_pending is None or self._last_event_ts is None:
                return None
            if now - self._last_event_ts > self.alert_max_age_s:
                self._legacy_pending = None
                return None
            alert = self._legacy_pending
            self._legacy_pending = None
        return alert
