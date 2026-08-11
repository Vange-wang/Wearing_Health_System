"""LLM 抽象接口 + DeepSeek 实现（v0.1 非流式，Spec §3/§5/§6）。

可插拔：换引擎只改 config + 新增 LLMBase 实现，业务代码不动。
DeepSeek 直连，不信任环境代理（Spec §3：直连，不配代理）。
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("voice-bridge.llm")

# Spec §6 系统提示词（v0.1 固定，一字不改）
SYSTEM_PROMPT = """你是"小衡"，一个便携健康助手的语音助手。要求：
1. 回答简短口语化，一般不超过 50 字；能一句话说完就一句话。
2. 用户是通过语音对话，回复要像日常聊天，不要列点、不要 markdown。
3. 涉及健康数据的问题（心率/血氧/睡眠等）暂回答"健康数据监测功能即将上线"。"""


class LLMError(Exception):
    """LLM 阶段错误基类。"""


class LLMConfigError(LLMError):
    """配置缺失（如 API key）→ 500 config_error。"""


class LLMBase(ABC):
    @abstractmethod
    def chat(self, user_text: str) -> str:
        """用户文本 → 回复文本（非流式）。"""


class DeepSeekLLM(LLMBase):
    def __init__(self, api_key: str | None, base_url: str, model: str):
        if not api_key:
            raise LLMConfigError(f"{model} 的 API key 未配置（环境变量/ .env）")
        try:
            import httpx
            from openai import OpenAI
        except ImportError as e:
            raise LLMConfigError(f"openai/httpx 未安装: {e}") from e
        # trust_env=False：不信任 HTTPS_PROXY 等环境变量，保证 DeepSeek 直连（Spec §3）
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.Client(trust_env=False, timeout=30.0),
        )
        self.model = model
        logger.info("DeepSeek client ready: %s @ %s", model, base_url)

    def chat(self, user_text: str) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                stream=False,  # v0.1 非流式（阶段边界红线）
            )
        except Exception as e:
            raise LLMError(f"DeepSeek 调用失败: {e}") from e
        text = (resp.choices[0].message.content or "").strip()
        logger.info("LLM reply (%d chars): %s", len(text), text[:80])
        return text


def create_llm(cfg) -> LLMBase:
    """工厂：按 config 创建 LLM 实例（当前仅 DeepSeek）。"""
    return DeepSeekLLM(cfg.deepseek_api_key(), cfg.llm_base_url, cfg.llm_model)
