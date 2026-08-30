"""单一记忆源模块（v2，Spec 2026-08-20 单一记忆源方案）。

架构：Hermes 记忆为唯一正本（USER.md 画像 + MEMORY.md 事实）。
- 注入（读）：本地直读 USER.md 全文 + MEMORY.md 最近部分（≤ budget 字节）——零网络、量恒定，保首字延迟。
- 写入（提取）：后台调 memory_server `POST /api/v1/memory/fact` → 写 MEMORY.md（写入即共享，三端可见）。
- 删除（遗忘）：后台调 `DELETE /api/v1/memory/fact?keyword=` → 字段级删 USER.md + MEMORY.md（全端失效）。

本模块只负责「本地读取」+「HTTP 读写」封装；提取/注入编排在 llm.py。
"""
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("voice-bridge.memory")

# 读取 MEMORY.md 时的字节预算安全余量（防止单条超长截断到半条）
_TAIL_SAFE_MARGIN = 256


class MemoryClient:
    """单一记忆源客户端：注入本地读、写删走 HTTP（memory_server 8781）。"""

    def __init__(self, api_url: str, user_profile_path: Path, memory_file_path: Path,
                 inject_budget: int = 6144, timeout: float = 2.0):
        self.api_url = api_url.rstrip("/")
        self.user_profile_path = Path(user_profile_path)
        self.memory_file_path = Path(memory_file_path)
        self.inject_budget = int(inject_budget)
        self.timeout = timeout

    # ---------------- 注入（读）：本地文件，零网络 ----------------

    def _open_memory_file(self):
        return self.memory_file_path.open("rb")

    def load_recent(self) -> str:
        """读取 MEMORY.md 最近部分（≤ inject_budget 字节），供注入。

        只取文件尾部（最新的记忆在末尾），并尽量对齐到条目标识（§ / 换行）避免截半条。
        失败静默返回空串（不影响回复）。
        """
        try:
            if not self.memory_file_path.exists():
                return ""
            with self._open_memory_file() as memory_file:
                memory_file.seek(0, 2)
                size = memory_file.tell()
                if size <= 0:
                    return ""
                window = min(size, self.inject_budget + _TAIL_SAFE_MARGIN)
                memory_file.seek(size - window)
                raw = memory_file.read(window)

            if size <= self.inject_budget:
                tail = raw
            else:
                tail = raw[-self.inject_budget:]
                # Prefer a complete line within the exact injection budget.
                newline = tail.find(b"\n")
                if newline >= 0:
                    tail = tail[newline + 1:]

            # A single line may exceed the budget. Drop at most the split UTF-8
            # prefix rather than inserting replacement characters into memory.
            for prefix in range(min(4, len(tail) + 1)):
                try:
                    return tail[prefix:].decode("utf-8").strip()
                except UnicodeDecodeError as exc:
                    if exc.start > 3:
                        return ""
            return ""
        except Exception:
            return ""

    # ---------------- 写入 / 删除：HTTP（后台线程调用） ----------------

    def _post_json(self, path: str, payload: dict) -> bool:
        import json
        import urllib.request

        url = f"{self.api_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url, data=data, method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.status == 200
            except Exception as e:
                logger.warning("memory 写入失败（第 %d 次）: %s", attempt + 1, e)
                time.sleep(0.3)
        return False

    def add_fact(self, category: str, fact: str, keywords: list[str] | None = None) -> bool:
        """写入一条事实（Hermes 侧去重 + 容量裁剪）。失败静默返回 False。"""
        payload = {
            "category": category or "general",
            "fact": fact.strip(),
            "keywords": [k.strip() for k in (keywords or []) if k.strip()],
        }
        if not payload["fact"]:
            return False
        return self._post_json("/fact", payload)

    def remove_by_keyword(self, keyword: str) -> int:
        """按关键词字段级删除（USER.md + MEMORY.md）。返回删除条数（失败返回 0）。"""
        import urllib.parse
        import urllib.request

        keyword = keyword.strip()
        if len(keyword) < 2:
            return 0
        url = f"{self.api_url}/fact?keyword={urllib.parse.quote(keyword)}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, method="DELETE")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    import json
                    try:
                        return int(json.loads(body).get("removed", 0))
                    except Exception:
                        return 1 if resp.status == 200 else 0
            except Exception as e:
                logger.warning("memory 删除失败（第 %d 次）: %s", attempt + 1, e)
                time.sleep(0.3)
        return 0
