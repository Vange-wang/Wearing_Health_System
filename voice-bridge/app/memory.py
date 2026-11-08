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
import json
import uuid
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("voice-bridge.memory")

# 读取 MEMORY.md 时的字节预算安全余量（防止单条超长截断到半条）
_TAIL_SAFE_MARGIN = 256


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    status: str
    attempts: int = 0
    http_status: int | None = None
    removed: int | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # bearer never follows even a same-host redirect


class MemoryClient:
    """单一记忆源客户端：注入本地读、写删走 HTTP（memory_server 8781）。"""

    def __init__(self, api_url: str, user_profile_path: Path, memory_file_path: Path,
                 inject_budget: int = 6144, timeout: float = 2.0, *, api_key: str | None = None):
        self.api_url = api_url.rstrip("/")
        self.user_profile_path = Path(user_profile_path)
        self.memory_file_path = Path(memory_file_path)
        self.inject_budget = int(inject_budget)
        self.timeout = timeout
        self._api_key = api_key
        self._results = threading.local()
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    @property
    def operation_result(self) -> OperationResult:
        return getattr(self._results, "last", OperationResult("", "not_started"))

    def _result(self, operation_id, status, attempts=0, http_status=None, removed=None):
        value = OperationResult(operation_id, status, attempts, http_status, removed)
        self._results.last = value
        logger.info("memory operation id=%s status=%s attempts=%d http=%s",
                    operation_id, status, attempts, http_status)
        return value

    def _request(self, method, path, payload=None):
        operation_id = uuid.uuid4().hex
        key = self._api_key
        if not key or not isinstance(key, str) or any(c in key for c in "\r\n"):
            return self._result(operation_id, "auth_unconfigured")
        try:
            endpoint = urllib.parse.urlsplit(self.api_url)
            local = (endpoint.scheme in ("http", "https") and endpoint.hostname in ("localhost", "127.0.0.1", "::1")
                     and endpoint.username is None and endpoint.password is None
                     and not endpoint.query and not endpoint.fragment)
        except ValueError:
            local = False
        if not local:
            return self._result(operation_id, "endpoint_invalid")
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, 3):
            code = None
            try:
                req = urllib.request.Request(self.api_url + path, data=data, method=method,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
                with self._opener.open(req, timeout=self.timeout) as response:
                    code = response.status
                    raw = response.read(65537)
                if code != 200:
                    status = "http_rejected"
                    if code >= 500 and attempt == 1:
                        time.sleep(.3); continue
                    return self._result(operation_id, status, attempt, code)
                try:
                    body = json.loads(raw.decode("utf-8")) if len(raw) <= 65536 else None
                    valid = isinstance(body, dict) and body.get("ok") is True
                    removed = body.get("removed") if valid and method == "DELETE" else None
                    if method == "DELETE":
                        valid = valid and type(removed) is int and removed >= 0
                except (ValueError, UnicodeError, RecursionError):
                    valid, removed = False, None
                if not valid:
                    return self._result(operation_id, "invalid_response", attempt, code)
                return self._result(operation_id, "no_match" if method == "DELETE" and removed == 0 else "success",
                                    attempt, code, removed)
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                if code in (401, 403):
                    return self._result(operation_id, "auth_rejected", attempt, code)
                if code < 500:
                    return self._result(operation_id, "http_rejected", attempt, code)
                status = "http_rejected"
            except (urllib.error.URLError, OSError, TimeoutError):
                status = "network_error"
            except Exception:
                return self._result(operation_id, "transport_error", attempt, code)
            if attempt == 1:
                time.sleep(.3)
        return self._result(operation_id, status, 2, code)

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
        return self._request("POST", path, payload).status == "success"

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
        keyword = keyword.strip()
        if len(keyword) < 2:
            return 0
        result = self._request("DELETE", "/fact?keyword=" + urllib.parse.quote(keyword))
        return result.removed if result.status in ("success", "no_match") else 0
