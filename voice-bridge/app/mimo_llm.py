"""MiMo V2.6 Pro behind existing history/profile/health-context interface."""
import threading
import time
from types import SimpleNamespace

from .llm import LightweightLLM, LLMError, LLMConfigError
from .mimo_tts import BASE_URL, read_mimo_settings
from .stream_resources import OwnedSyncStream

MODEL = "mimo-v2.6-pro"


class _PinnedClient:
    """Pin all chat, warmup, heartbeat and memory-extraction requests."""
    def __init__(self, sdk, model=MODEL):
        self._sdk = sdk
        self.model = model
        sdk.max_retries = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        kwargs["model"] = self.model
        cap = kwargs.pop("max_tokens", 512)
        kwargs["max_tokens" if self.model.startswith("deepseek") else "max_completion_tokens"] = cap
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            return self._sdk.chat.completions.create(**kwargs)
        except Exception:
            raise LLMError("Direct LLM request failed") from None

    def close(self):
        self._sdk.close()


class MiMoLLM(LightweightLLM):
    name = "mimo"
    model = MODEL
    tools_available = False
    memory_extract_attempts = 1
    allowed_response_models = frozenset({MODEL})

    def __init__(self, user_profile_path, memory_store=None, conversation_history=None):
        try:
            key = read_mimo_settings()
        except Exception:
            raise LLMConfigError("MiMo project credential unavailable") from None
        super().__init__(key, BASE_URL, MODEL, user_profile_path,
                         memory_store=memory_store, conversation_history=conversation_history)
        self.client = _PinnedClient(self.client)
        self.last_call_ok = None
        self.last_response_model = None

    def _system_prompt(self, user_text=""):
        return super()._system_prompt(user_text) + (
            "\n\n本次语音试运行会话没有联网搜索、天气查询、写文件、发邮件等工具执行能力。"
            "涉及这些实时查询或外部操作时，直接说明当前无法执行；不得假称已查询、已发送或已完成。"
        )

    def chat(self, user_text):
        self.last_call_ok = None
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=self._get_messages(user_text), stream=False)
            if response.model not in self.allowed_response_models:
                raise ValueError()
            self.last_response_model = response.model
            text = response.choices[0].message.content
            if not isinstance(text, str) or not text.strip():
                raise ValueError()
        except Exception:
            self.last_call_ok = False
            raise LLMError("Direct LLM response contract invalid") from None
        self.last_call_ok = True
        self._remember(user_text, text)
        return text

    def stream_chat(self, user_text):
        self.last_call_ok = None
        started = time.perf_counter()
        stats = {"tool_seen": False, "first_chunk_ms": None, "first_content_ms": None}
        self.stats = stats
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=self._get_messages(user_text), stream=True)
        except Exception:
            self.last_call_ok = False
            raise LLMError("Direct LLM request failed") from None
        collected = []

        def content():
            terminal = False
            try:
                for chunk in response:
                    if getattr(chunk, "model", None) not in self.allowed_response_models:
                        raise ValueError()
                    self.last_response_model = chunk.model
                    if stats["first_chunk_ms"] is None:
                        stats["first_chunk_ms"] = round((time.perf_counter() - started) * 1000)
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish = chunk.choices[0].finish_reason
                    if finish is not None:
                        if finish != "stop":
                            raise ValueError()
                        terminal = True
                    text = getattr(delta, "content", None)
                    if text:
                        if not isinstance(text, str):
                            raise ValueError()
                        if stats["first_content_ms"] is None:
                            stats["first_content_ms"] = round((time.perf_counter() - started) * 1000)
                        collected.append(text)
                        yield text
                if not collected or not terminal:
                    raise ValueError()
                self.last_call_ok = True
            except Exception:
                self.last_call_ok = False
                raise LLMError("Direct LLM stream failed") from None

        return OwnedSyncStream(content(), response, stats,
                               lambda: self._remember(user_text, "".join(collected)))

    def warmup(self):
        # Same public warmup as the previous backend; no transcript logging.
        try:
            self.client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": "你好"}],
                max_tokens=1, stream=False)
        except LLMError:
            pass

    def start_heartbeat(self, interval=240):
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop,
                                                   args=(interval,), daemon=True,
                                                   name=f"{self.name}-heartbeat")
        self._heartbeat_thread.start()

    def _heartbeat_loop(self, interval):
        while not self._heartbeat_stop.wait(interval):
            self.warmup()


class DeepSeekVoiceLLM(MiMoLLM):
    """Selected by Root's same-condition benchmark; uses only the DeepSeek key."""
    name = "deepseek"

    def _system_prompt(self, user_text=""):
        if getattr(self, 'direct_weather_configured', False):
            return LightweightLLM._system_prompt(self, user_text) + '\n系统有独立的当前天气数据通道，已核验新加坡、北京、上海。缺地点请澄清；其他地点尚未完成可靠匹配。当前模型不执行查询，不得编造实时天气。外部写入操作未启用。'
        if not getattr(self, "tool_route_configured", False):
            return super()._system_prompt(user_text)
        return LightweightLLM._system_prompt(self, user_text) + (
            "\n\n系统已配置独立的 Hermes 工具通道，可发起联网搜索和天气查询。"
            "但本次轻量回答没有执行工具，不能生成或猜测实时天气、搜索结果、来源或成功状态。"
            "用户询问系统能否查询时，说明可通过工具通道查询；需要地点时请其说明地点。"
            "不要把当前轻量模型没有工具误说成整个系统禁止联网。"
            "实际查询由工具通道路由处理；工具失败应据实说明失败，不伪称查询成功。"
        )

    def __init__(self, api_key, base_url, model, user_profile_path,
                 memory_store=None, conversation_history=None, tool_route_configured=False):
        if base_url.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"} or model != "deepseek-chat":
            raise LLMConfigError("DeepSeek trial endpoint/model invalid")
        LightweightLLM.__init__(self, api_key, base_url, model, user_profile_path,
                               memory_store=memory_store, conversation_history=conversation_history)
        self.client = _PinnedClient(self.client, model)
        self.allowed_response_models = frozenset({model, "deepseek-flash"})
        self.tool_route_configured = bool(tool_route_configured)
        self.last_call_ok = None
        self.last_response_model = None
