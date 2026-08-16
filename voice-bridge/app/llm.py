"""LLM 抽象接口 + 双后端（长期 RAG，Spec A1 修订「分路」）。

- 慢路径 = Hermes API Server（OpenAI 兼容），voice-bridge 只负责「听/说」，
  「想」交给 Hermes（与微信共用同一 profile 的 persistent memory + skills）。
- 轻量通道 = DeepSeek 裸模型 + USER.md 注入（纯闲聊/简单问答，~1.5s）。

流式细节（Spec §4 / §9 风险表）：
- Hermes agent 可能先跑工具（SSE 里只有工具指示、无正文），最后才流式出答案。
  stream_chat() 过滤工具指示事件（tool_calls delta），只产出正文文本；
  同时在 self.stats 记录 first_chunk_ms / first_content_ms / tool_seen，
  供 pipeline 做「工具期 / 答案期」分段计量。
- 直连：trust_env=False，不信任环境代理（与 v0.1/v0.2 一致）。
"""
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path

logger = logging.getLogger("voice-bridge.llm")

# ISSUE-0008：轻量通道多轮上下文（指代消解）。
# 轻量通道每轮独立 messages 导致「A城市天气 → B城市呢」无法理解指代，
# 此处维护一个滑动窗口会话历史（最近 N 轮），并设置无交互过期避免久远串上下文。
HISTORY_MAX_MESSAGES = 8   # 最近 4 轮（4 user + 4 assistant）
SESSION_TTL_SECONDS = 600  # 10 分钟无交互则清空历史

# 方案1（延迟优化）：DeepSeek 连接保温。A7 只在启动预热一次，长时间无请求后
# TLS 连接被 DeepSeek 服务端回收，首请求付冷连接 ~1.4s（热连接仅 ~0.6s）。
# 周期心跳（max_tokens=1 最小请求）保持连接热，llm_ttft 稳定 ~500ms。
HEARTBEAT_INTERVAL_SECONDS = 240  # 每 4 分钟一次（< TLS 空闲超时，保守）

# 慢路径哨兵：SSE 首次出现工具调用时，stream_chat 产出此对象一次，
# 供 pipeline 触发「安抚语第一帧」（A5）。不进分句器，不污染正文。
TOOL_SENTINEL = object()

# 人设 + 情感化系统提示词（Hermes 起草，参照小智默认人设；轻量通道与慢路径共用基调）
SYSTEM_PROMPT = """你是小V，一个聪明友善、活泼亲切的健康助手，陪伴用户的可穿戴健康设备。

说话风格：
- 像真人朋友聊天，自然口语化，带点情绪和幽默，不要书面腔、机器人腔、客套话。
- 适当用语气词（嗯、哈哈、哦、呀、嘞）和情感标点（！？～…）。
- 提到健康、身体、心情时带一点体贴（例如「要注意休息哦～」「最近睡得好吗？」）。
- 回答简短，1~2 句为主，适合语音朗读，句号或问号结尾。

功能约束：
- 健康数据（心率、血氧、睡眠等）实时监测功能尚未接入，被问到时诚实说「这个功能还在准备中，接入后就能帮你看了」，不要编造数据。
- 实时数据（天气、快递、新闻、股票、路况等）你无法联网查询时，诚实说「这个我暂时查不了，需要联网搜索」，禁止编造具体数值。
- 不主动编造任何具体数据或事实。
- 不主动自我介绍，直接回答用户问题；除非用户明确问「你是谁/你叫什么名字」。"""


class LLMError(Exception):
    """LLM 阶段错误基类。"""


class LLMConfigError(LLMError):
    """配置缺失（如 API_SERVER_KEY）→ 500 config_error。"""


class LLMBase(ABC):
    name: str = "unknown"

    @abstractmethod
    def chat(self, user_text: str) -> str:
        """用户文本 → 回复文本（非流式，v0.1 路径保留）。"""

    @abstractmethod
    def stream_chat(self, user_text: str):
        """用户文本 → 正文增量迭代器（Iterator[str]，工具指示已过滤）。"""


class HermesLLM(LLMBase):
    """Hermes API Server 后端（OpenAI 兼容 /v1/chat/completions）。"""

    name = "hermes"

    def __init__(self, api_key: str | None, base_url: str, model: str):
        if not api_key:
            raise LLMConfigError(
                "Hermes API Server key 未配置（环境变量/ .env，需先在 Hermes 侧 "
                "hermes config set API_SERVER_ENABLED true + API_SERVER_KEY）"
            )
        try:
            import httpx
            from openai import OpenAI
        except ImportError as e:
            raise LLMConfigError(f"openai/httpx 未安装: {e}") from e
        # trust_env=False：不信任 HTTPS_PROXY 等环境变量，本机直连（Spec §3）
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.Client(trust_env=False, timeout=60.0),
        )
        self.model = model
        # 分段计量（每次 stream_chat 重置）：tool_seen / first_chunk_ms / first_content_ms
        self.stats: dict = {}
        logger.info("Hermes client ready: %s @ %s", model, base_url)

    def chat(self, user_text: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                stream=False,  # v0.1 非流式路径保留
            )
        except Exception as e:
            raise LLMError(f"Hermes 调用失败: {e}") from e
        text = (resp.choices[0].message.content or "").strip()
        logger.info("LLM reply (%d chars): %s", len(text), text[:80])
        return text

    def stream_chat(self, user_text: str):
        """流式：产出正文增量；工具调用只标记、不透出。

        Hermes API Server 的 `/v1/chat/completions` 是**真 agent（跑工具循环）**，
        但响应体 `tool_calls` 字段天然为空——工具调用通过 SSE 的
        `event: hermes.tool.progress` 事件暴露（见查证结论：纯聊天透传是误判）。
        故此处用 httpx 直读 SSE，监听该事件判 tool_seen。

        self.stats 在流结束后可读：
        - first_chunk_ms：首个 SSE chunk 到达（相对流开始）
        - first_content_ms：首个正文 delta 到达（无正文=工具期长度近似）
        - tool_seen：是否出现工具调用（hermes.tool.progress 事件或 tool_calls delta）
        """
        import json

        import httpx

        self.stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}
        t0 = time.perf_counter()
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "stream": True,
        }
        stream_client = httpx.Client(trust_env=False, timeout=180.0)
        try:
            req = stream_client.build_request("POST", url, json=body, headers=headers)
            resp = stream_client.send(req, stream=True)
        except Exception as e:
            stream_client.close()
            raise LLMError(f"Hermes 流式调用失败: {e}") from e

        stats = self.stats

        def _iter():
            sentinel_sent = False
            try:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    # 非标准事件：hermes.tool.progress → 工具调用（真 agent 工具循环）
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                        if ev == "hermes.tool.progress":
                            stats["tool_seen"] = True
                            if not sentinel_sent:
                                sentinel_sent = True
                                yield TOOL_SENTINEL
                        continue
                    if not line.startswith("data:"):
                        continue
                    d = line[5:].strip()
                    if not d or d == "[DONE]":
                        continue
                    if stats["first_chunk_ms"] is None:
                        stats["first_chunk_ms"] = round((time.perf_counter() - t0) * 1000)
                    try:
                        obj = json.loads(d)
                    except Exception:
                        continue
                    if "choices" not in obj:
                        continue
                    delta = obj["choices"][0].get("delta") or {}
                    # 标准 tool_calls delta（若 Hermes 某些场景透出）
                    if delta.get("tool_calls"):
                        stats["tool_seen"] = True
                        if not sentinel_sent:
                            sentinel_sent = True
                            yield TOOL_SENTINEL
                        continue
                    content = delta.get("content")
                    if content:
                        if stats["first_content_ms"] is None:
                            stats["first_content_ms"] = round((time.perf_counter() - t0) * 1000)
                        yield content
            except Exception as e:
                raise LLMError(f"Hermes 流式读取失败: {e}") from e
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
                try:
                    stream_client.close()
                except Exception:
                    pass

        return _iter()


def load_user_profile(path) -> tuple[str, bool]:
    """只读 Hermes USER.md（用户画像，裁决①：只注入 USER.md，不读 MEMORY.md）。

    返回 (内容, 是否成功)。文件不存在/读取失败 → ("", False)。
    """
    try:
        p = Path(path)
        if not p.exists():
            return "", False
        return p.read_text(encoding="utf-8").strip(), True
    except Exception:
        return "", False


class LightweightLLM(LLMBase):
    """轻量通道（长期 RAG A1 修订「分路」）：DeepSeek 裸模型 + USER.md 注入。

    - 直连 DeepSeek（trust_env=False），无工具、无 skills → ~1.5s 开口。
    - 每次请求读 Hermes USER.md 注入 system prompt（共用记忆；红线：必须注入）。
    - USER.md 读取失败 → 抛 LLMError（由 pipeline 降级慢路径），不退回无记忆裸聊。
    """

    name = "deepseek"

    def __init__(self, api_key: str | None, base_url: str, model: str, user_profile_path):
        if not api_key:
            raise LLMConfigError(
                "轻量通道 DeepSeek key 未配置（环境变量/ .env）"
            )
        try:
            import httpx
            from openai import OpenAI
        except ImportError as e:
            raise LLMConfigError(f"openai/httpx 未安装: {e}") from e
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.Client(trust_env=False, timeout=60.0),
        )
        self.model = model
        self.user_profile_path = user_profile_path
        self.stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}
        # ISSUE-0008：滑动窗口会话历史（多轮指代消解）。
        # 单会话（当前单 BOX-3 设备）；多设备时需按来源区分会话。
        self._history: deque = deque(maxlen=HISTORY_MAX_MESSAGES)
        self._history_lock = threading.Lock()
        self._last_active = time.time()
        # 方案1：心跳保温线程（保持 DeepSeek TLS 连接热）
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        logger.info("Lightweight(DeepSeek) ready: %s @ %s", model, base_url)

    def _system_prompt(self) -> str:
        profile, ok = load_user_profile(self.user_profile_path)
        if not ok:
            raise LLMError("USER.md 读取失败（轻量通道共用记忆无法注入）")
        return (
            SYSTEM_PROMPT
            + "\n\n以下是用户的长期画像与偏好（来自共享记忆），回复时自然贴合：\n"
            + profile
        )

    def _get_messages(self, user_text: str) -> list[dict]:
        """构造带历史的 messages（ISSUE-0008）：system + 最近 N 轮历史 + 当前 user。

        超过 SESSION_TTL_SECONDS 无交互则清空历史，避免久远对话串上下文。
        """
        system = self._system_prompt()
        now = time.time()
        with self._history_lock:
            if now - self._last_active > SESSION_TTL_SECONDS:
                self._history.clear()
            history = list(self._history)
            self._last_active = now
        return [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_text}]

    def _remember(self, user_text: str, assistant_text: str) -> None:
        """把一轮对话（user + assistant）追加进历史（ISSUE-0008）。"""
        assistant_text = (assistant_text or "").strip()
        if not assistant_text:
            return
        with self._history_lock:
            self._history.append({"role": "user", "content": user_text})
            self._history.append({"role": "assistant", "content": assistant_text})
            self._last_active = time.time()

    def clear_history(self) -> None:
        """清空会话历史（测试/手动重置用）。"""
        with self._history_lock:
            self._history.clear()

    def chat(self, user_text: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=self._get_messages(user_text),
                stream=False,
            )
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"DeepSeek 调用失败: {e}") from e
        text = (resp.choices[0].message.content or "").strip()
        self._remember(user_text, text)
        return text

    def stream_chat(self, user_text: str):
        t0 = time.perf_counter()
        self.stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}
        try:
            messages = self._get_messages(user_text)
        except LLMError:
            raise
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
            )
        except Exception as e:
            raise LLMError(f"DeepSeek 流式调用失败: {e}") from e

        stats = self.stats

        def _iter():
            collected: list[str] = []
            try:
                for chunk in stream:
                    if stats["first_chunk_ms"] is None:
                        stats["first_chunk_ms"] = round((time.perf_counter() - t0) * 1000)
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue
                    content = getattr(delta, "content", None)
                    if content:
                        if stats["first_content_ms"] is None:
                            stats["first_content_ms"] = round((time.perf_counter() - t0) * 1000)
                        collected.append(content)
                        yield content
            except Exception as e:
                raise LLMError(f"DeepSeek 流式读取失败: {e}") from e
            # 流正常结束：把这一轮记入历史（ISSUE-0008）
            self._remember(user_text, "".join(collected))

        return _iter()

    def warmup(self) -> None:
        """A7 启动预热：发最小请求（max_tokens=1），预热 TLS 连接 + 首 token。

        把「拨号 + 叫醒」的一次性冷启动成本花在服务启动时刻，
        首次按键即热连接（省 ~2s）。同步阻塞，调用方放后台线程。
        """
        try:
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=1,
                stream=False,
            )
            logger.info("DeepSeek 预热完成（连接 + 首 token 就绪）")
        except Exception as e:
            logger.warning("DeepSeek 预热失败（首次请求付冷启动，不影响服务）: %s", e)

    def start_heartbeat(self, interval: float = HEARTBEAT_INTERVAL_SECONDS) -> None:
        """方案1：启动周期心跳（后台守护线程），保持 DeepSeek TLS 连接热。

        消除「长时间无请求 → 连接被服务端回收 → 首请求付冷连接 ~1.4s」的尖峰。
        """
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval,),
            daemon=True,
            name="deepseek-heartbeat",
        )
        self._heartbeat_thread.start()
        logger.info("DeepSeek 心跳保温启动（每 %ds 一次）", interval)

    def stop_heartbeat(self) -> None:
        """停止心跳（服务关闭时调用）。"""
        self._heartbeat_stop.set()

    def _heartbeat_loop(self, interval: float) -> None:
        while not self._heartbeat_stop.is_set():
            self._heartbeat_stop.wait(interval)
            if self._heartbeat_stop.is_set():
                break
            try:
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "你好"}],
                    max_tokens=1,
                    stream=False,
                )
                logger.debug("DeepSeek 心跳保温 OK")
            except Exception as e:
                logger.debug("DeepSeek 心跳失败（下次重试）: %s", e)


def create_llm(cfg) -> LLMBase:
    """工厂：慢路径 = Hermes 后端。"""
    return HermesLLM(cfg.llm_api_key(), cfg.llm_api_server_url, cfg.llm_model)


def create_lightweight_llm(cfg) -> LLMBase:
    """工厂：轻量通道 = DeepSeek 裸模型 + USER.md 注入。"""
    return LightweightLLM(
        cfg.lightweight_api_key(), cfg.lw_base_url, cfg.lw_model, cfg.user_profile_path
    )
