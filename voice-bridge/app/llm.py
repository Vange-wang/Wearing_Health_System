"""LLM 抽象接口 + Hermes API Server 实现（v0.3，Spec v0.3 §3/§5 A1）。

v0.3 起 LLM 后端 = Hermes API Server（OpenAI 兼容），voice-bridge 只负责「听/说」，
「想」交给 Hermes（与微信共用同一 profile 的 persistent memory + skills）。
A1 裁决：彻底停用自带 DeepSeek，本文件不存在 DeepSeek 调用路径，不留兜底。

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

logger = logging.getLogger("voice-bridge.llm")

# 慢路径哨兵：SSE 首次出现工具调用时，stream_chat 产出此对象一次，
# 供 pipeline 触发「安抚语第一帧」（A5）。不进分句器，不污染正文。
TOOL_SENTINEL = object()

# Spec §7 系统提示词（v0.2 微调版沿用：第 4 条"句号结尾"）
SYSTEM_PROMPT = """你是"小衡"，一个便携健康助手的语音助手。要求：
1. 回答简短口语化，一般不超过 50 字；能一句话说完就一句话。
2. 用户是通过语音对话，回复要像日常聊天，不要列点、不要 markdown。
3. 涉及健康数据的问题（心率/血氧/睡眠等）暂回答"健康数据监测功能即将上线"。
4. 回答尽量用句号结尾，方便播报分句。"""


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


def create_llm(cfg) -> LLMBase:
    """工厂：v0.3 起仅 Hermes 后端（A1：不留 DeepSeek 兜底）。"""
    return HermesLLM(cfg.llm_api_key(), cfg.llm_api_server_url, cfg.llm_model)
