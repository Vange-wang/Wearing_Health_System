"""健康数据缓存 + 阈值预警判定（BLE 立项 Spec §5/§6）。

- P3 骨架：数据接收缓存 + 新鲜度判断（供 DATA 路由模板直答）。
- P4 预警：连续 N 次超阈值 + 冷却（供 /health/alert 轮询）。
- 微信日上限在三路推送层（main.py）做，本模块只负责「是否触发预警」。

单 BOX-3 设备场景：内存缓存即可（多设备时需按来源分桶）。
"""
import logging
import threading
import time

logger = logging.getLogger("voice-bridge.health")


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
    ):
        self.hr_high = hr_high
        self.hr_low = hr_low
        self.hr_low_night = hr_low_night
        self.spo2_low = spo2_low
        self.night_start = night_start
        self.night_end = night_end
        self.alert_consecutive = alert_consecutive
        self.alert_cooldown_s = alert_cooldown_s

        self._lock = threading.Lock()
        self._hr: float | None = None
        self._spo2: float | None = None
        self._ts: float | None = None  # 最近更新（time.monotonic）
        self._seq: int | None = None

        # 预警状态：连续超阈值计数 + 上次触发时刻
        self._over_count = 0
        self._last_alert_ts: float | None = None

    def update(self, hr: float | None, spo2: float | None, seq: int | None = None) -> None:
        """接收一帧数据（hr BPM / spo2 %，None 表示该字段无效）。"""
        now = time.monotonic()
        with self._lock:
            self._hr = hr
            self._spo2 = spo2
            self._seq = seq
            self._ts = now
            if self._is_over(hr, spo2):
                self._over_count += 1
            else:
                self._over_count = 0
        logger.debug("health update hr=%s spo2=%s seq=%s over_count=%d", hr, spo2, seq, self._over_count)

    def get_latest(self) -> tuple[float | None, float | None, float | None]:
        """返回 (hr, spo2, age_seconds)。无数据返回 (None, None, None)。"""
        with self._lock:
            if self._ts is None:
                return None, None, None
            return self._hr, self._spo2, time.monotonic() - self._ts

    def has_data_within(self, seconds: float) -> bool:
        """最近 seconds 秒内是否有有效数据（新鲜度判断）。"""
        _, _, age = self.get_latest()
        return age is not None and age <= seconds

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
        """BOX-3 轮询：有预警触发返回预警信息，否则 None。

        触发条件：连续 alert_consecutive 次超阈值 + 距上次触发超过冷却期。
        触发后重置计数（等下一轮连续超阈值），避免重复触发。
        """
        now = time.monotonic()
        with self._lock:
            if self._over_count < self.alert_consecutive:
                return None
            if self._last_alert_ts is not None and now - self._last_alert_ts < self.alert_cooldown_s:
                return None
            self._last_alert_ts = now
            self._over_count = 0
            hr, spo2 = self._hr, self._spo2
        logger.warning("健康预警触发: hr=%s spo2=%s", hr, spo2)
        return {"hr": hr, "spo2": spo2}
