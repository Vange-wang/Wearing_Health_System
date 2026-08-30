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
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("voice-bridge.health")


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

    def update(
        self,
        hr: float | None,
        spo2: float | None,
        seq: int | None = None,
        flags: int | None = None,
        quality: float = 1.0,
    ) -> None:
        """接收一帧数据（hr BPM / spo2 %，None 表示该字段无效）。

        None 字段保留上一有效值，但不会刷新该字段时间戳。bit0/bit1 是
        HR/SpO2 有效位，bit2 是运动伪影。伪影或低质量帧只刷新链路状态，
        不刷新生理字段，也不中累计连续异常。
        """
        now = self._monotonic()
        if flags is None:
            flags = (0x01 if hr is not None else 0) | (0x02 if spo2 is not None else 0)
        quality_ok = 0.0 <= quality <= 1.0 and quality >= self.min_quality
        artifact = bool(flags & 0x04)
        hr_valid = quality_ok and not artifact and bool(flags & 0x01) and hr is not None
        spo2_valid = quality_ok and not artifact and bool(flags & 0x02) and spo2 is not None
        accepted_hr = hr if hr_valid else None
        accepted_spo2 = spo2 if spo2_valid else None
        fire: dict | None = None
        with self._lock:
            self._link_ts = now
            self._seq = seq
            self._flags = flags
            self._quality = quality
            if hr_valid:
                self._hr = hr
                self._hr_ts = now
            if spo2_valid:
                self._spo2 = spo2
                self._spo2_ts = now
            # 只判定本帧通过质量门的字段；陈旧合并值不得维持异常计数。
            if (hr_valid or spo2_valid) and self._is_over(accepted_hr, accepted_spo2):
                self._over_count += 1
            else:
                self._over_count = 0
                self._episode_active = False
            # 达阈值开启 episode；异常持续时每过 cooldown 生成一个新事件。
            if (
                self._over_count >= self.alert_consecutive
                and (
                    not self._episode_active
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
