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
import time
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("voice-bridge.llm")

# 慢路径哨兵：SSE 首次出现工具调用时，stream_chat 产出此对象一次，
# 供 pipeline 触发「安抚语第一帧」（A5）。不进分句器，不污染正文。
TOOL_SENTINEL = object()

# Spec §7 系统提示词（v0.2 微调版沿用：第 4 条"句号结尾"、第 5 条"不主动自我介绍"）
SYSTEM_PROMPT = """你是"小衡"，一个便携健康助手的语音助手。要求：
1. 回答简短口语化，一般不超过 50 字；能一句话说完就一句话。
2. 用户是通过语音对话，回复要像日常聊天，不要列点、不要 markdown。
3. 涉及健康数据的问题（心率/血氧/睡眠等）暂回答"健康数据监测功能即将上线"。
4. 回答尽量用句号结尾，方便播报分句。
5. 不要主动自我介绍（如"我是小衡/你的健康助手"），直接回答用户问题；除非用户明确问"你是谁/你叫什么名字"。"""


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
        """流式：产出正文增量；工具指示（tool_calls）只标记、不透出。

        self.stats 在流结束后可读：
        - first_chunk_ms：首个 SSE chunk 到达（相对流开始）
        - first_content_ms：首个正文 delta 到达（无正文=工具期长度近似）
        - tool_seen：是否出现工具调用
        """
        self.stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}
        t0 = time.perf_counter()
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                stream=True,  # v0.2/v0.3 流式
            )
        except Exception as e:
            raise LLMError(f"Hermes 流式调用失败: {e}") from e

        stats = self.stats

        def _iter():
            try:
                sentinel_sent = False
                for chunk in stream:
                    if stats["first_chunk_ms"] is None:
                        stats["first_chunk_ms"] = round((time.perf_counter() - t0) * 1000)
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue
                    # 工具指示事件：标记 + 过滤，不进分句器（Spec §9 风险表）；
                    # 首次出现时产出一次 TOOL_SENTINEL，供 pipeline 发安抚语（A5）
                    if getattr(delta, "tool_calls", None):
                        stats["tool_seen"] = True
                        if not sentinel_sent:
                            sentinel_sent = True
                            yield TOOL_SENTINEL
                        continue
                    if getattr(delta, "role", None) == "tool":
                        stats["tool_seen"] = True
                        continue
                    content = getattr(delta, "content", None)
                    if content:
                        if stats["first_content_ms"] is None:
                            stats["first_content_ms"] = round((time.perf_counter() - t0) * 1000)
                        yield content
            except Exception as e:
                raise LLMError(f"Hermes 流式读取失败: {e}") from e

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

    def chat(self, user_text: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": user_text},
                ],
                stream=False,
            )
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"DeepSeek 调用失败: {e}") from e
        return (resp.choices[0].message.content or "").strip()

    def stream_chat(self, user_text: str):
        t0 = time.perf_counter()
        self.stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}
        try:
            system = self._system_prompt()
        except LLMError:
            raise
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
                stream=True,
            )
        except Exception as e:
            raise LLMError(f"DeepSeek 流式调用失败: {e}") from e

        stats = self.stats

        def _iter():
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
                        yield content
            except Exception as e:
                raise LLMError(f"DeepSeek 流式读取失败: {e}") from e

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


def create_llm(cfg) -> LLMBase:
    """工厂：慢路径 = Hermes 后端。"""
    return HermesLLM(cfg.llm_api_key(), cfg.llm_api_server_url, cfg.llm_model)


def create_lightweight_llm(cfg) -> LLMBase:
    """工厂：轻量通道 = DeepSeek 裸模型 + USER.md 注入。"""
    return LightweightLLM(
        cfg.lightweight_api_key(), cfg.lw_base_url, cfg.lw_model, cfg.user_profile_path
    )
