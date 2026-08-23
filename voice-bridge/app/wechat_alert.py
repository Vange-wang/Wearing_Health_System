"""P4 微信预警推送（Spec §5.3/§5.4）：hermes send 后台异步 + 日上限 5 条。

- 异步：threading 守护线程跑 hermes send，不进语音首字路径；
- 日上限：计数 + 日期，持久化到 state_file（跨重启生效），次日自动重置；
- 降级：推送失败记日志（限频），不影响任何链路；
- iLink 配额 24h/10 条（Spec），日上限 5 条留有余量。
"""
import json
import logging
import subprocess
import threading
from datetime import date
from pathlib import Path

logger = logging.getLogger("voice-bridge.wechat_alert")

HERMES_EXE = r"D:\miniconda\Scripts\hermes.exe"
PUSH_TIMEOUT_S = 30


class WechatAlertPusher:
    """预警消息推送器：限流 + 异步 hermes send。"""

    def __init__(self, chat_id: str, daily_limit: int = 5,
                 state_file: str | None = None, enabled: bool = True):
        self.chat_id = chat_id
        self.daily_limit = daily_limit
        self.state_file = Path(state_file) if state_file else None
        self.enabled = enabled and bool(chat_id)

        self._lock = threading.Lock()
        self._today: date | None = None
        self._count = 0
        self._load_state()

    # ---- 日限状态（持久化，跨重启） ----
    def _load_state(self) -> None:
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self._today = date.fromisoformat(data["date"])
            self._count = int(data["count"])
            logger.info("微信推送状态载入：%s 已推 %d/%d", self._today, self._count, self.daily_limit)
        except Exception:
            logger.warning("微信推送状态文件损坏，忽略")

    def _save_state(self) -> None:
        if self.state_file is None or self._today is None:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps({"date": self._today.isoformat(), "count": self._count}),
                encoding="utf-8")
        except Exception:
            logger.warning("微信推送状态持久化失败", exc_info=True)

    # ---- 对外入口（HealthDataStore.alert_cb） ----
    def push(self, hr: float | None, spo2: float | None) -> None:
        if not self.enabled:
            return
        with self._lock:
            today = date.today()
            if self._today != today:
                self._today = today
                self._count = 0
            if self._count >= self.daily_limit:
                logger.warning("微信预警日上限 %d 已到，跳过推送", self.daily_limit)
                return
            self._count += 1
            self._save_state()

        msg = self._build_message(hr, spo2)
        logger.info("触发微信预警推送（今日第 %d/%d 条）: %s", self._count, self.daily_limit, msg)
        threading.Thread(target=self._run_send, args=(msg,), daemon=True).start()

    @staticmethod
    def _build_message(hr: float | None, spo2: float | None) -> str:
        parts = []
        if hr is not None:
            parts.append(f"心率 {int(round(hr))}")
        if spo2 is not None:
            parts.append(f"血氧 {int(round(spo2))}%")
        detail = "、".join(parts) if parts else "检测数据"
        return f"健康提醒：最新检测异常（{detail}），建议关注一下。"

    def _run_send(self, msg: str) -> None:
        try:
            r = subprocess.run(
                [HERMES_EXE, "send", "-t", f"weixin:{self.chat_id}", msg],
                capture_output=True, text=True, timeout=PUSH_TIMEOUT_S)
            if r.returncode == 0:
                logger.info("微信预警推送成功: %s", msg)
            else:
                logger.error("微信预警推送失败 rc=%d: %s",
                             r.returncode, (r.stderr or "").strip()[:200])
        except Exception:
            logger.error("微信预警推送异常", exc_info=True)
