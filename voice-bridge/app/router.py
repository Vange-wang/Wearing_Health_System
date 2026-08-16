"""路由判定（长期 RAG，Spec §3 A2 四步规则）。

默认轻量（快），命中技能/工具需求走慢路径，命中知识库走 RAG。
ISSUE-0010：会话级路由记忆——上轮慢路径（查天气等）时，本轮指代追问
（「深圳的呢」）延续慢路径，避免跌回轻量通道 DeepSeek 裸模型编造实时数据。
"""
import logging
import time

logger = logging.getLogger("voice-bridge.router")

# 三类路由结果
LIGHTWEIGHT = "lightweight"
RAG = "rag"
HERMES = "hermes"

# 会话级路由记忆 TTL（对齐 LLM 历史 600s 过期；超时不再延续上一轮慢路径）
ROUTE_TTL_SECONDS = 600

# 指代/追问提示词：短句含这些词 → 视为上一轮的延续（而非全新话题）
FOLLOWUP_HINTS = ["呢", "那", "它", "这", "也", "还有", "多少", "几度", "几点"]

# 新话题启动信号：短句含这些词 → 是全新话题，不延续上一轮
# （覆盖常见动词 + 疑问结构；ASR 常丢"呢"等轻声词，故用反向信号兜底）
NEW_TOPIC_SIGNALS = [
    "讲", "说", "唱", "放", "开", "玩", "找", "帮", "搜", "写", "发", "定",
    "查", "看", "来", "做", "弄", "算", "问", "介绍", "解释", "讲个",
    "怎么办", "是什么", "为什么", "怎么样", "怎么", "如何", "什么",
]

# 能力询问提示词：问系统「能不能/能否/会不会」做某事（如「你能不能查天气」）。
# 这类是「问能力」，不是「下达查询命令」，不该触发工具、不该发安抚语。
CAPABILITY_HINTS = ["能不能", "能否", "会不会", "可不可以", "是否能够", "行不行", "能不能够", "你能", "你会"]

# 祈使/请求词：含这些词是「下达命令」（如「帮我查天气」「能帮我查吗」），
# 即使同时含能力提示词也按命令处理，走慢路径。
IMPERATIVE_HINTS = ["帮我", "替我", "给我", "请你", "麻烦"]

# 礼貌/结束语白名单：这些词不是追问，直接走快路径（否则慢路径后说「谢谢」会被判为追问 → 慢路径 10~18s）
POLITE_WHITELIST = ["谢谢", "再见", "晚安", "早安", "拜拜", "辛苦", "不用", "没事", "好的", "嗯嗯", "收到", "好嘞"]


class Router:
    def __init__(self, tool_keywords: list[str], skill_keywords: list[str]):
        self.tool_keywords = [k for k in tool_keywords if k]
        self.skill_keywords = [k for k in skill_keywords if k]
        # ISSUE-0010：上一轮路由（会话级记忆；单设备够用，多设备需按来源区分）
        self._last_route: str | None = None
        self._last_route_ts: float = 0.0  # _last_route 设置时刻（monotonic），用于 TTL 过期

    def _set_last_route(self, route: str) -> None:
        self._last_route = route
        self._last_route_ts = time.monotonic()

    def _route_memory_expired(self) -> bool:
        """上一轮路由记忆是否已过 TTL（超时不再延续慢路径）。"""
        if self._last_route is None:
            return True
        return (time.monotonic() - self._last_route_ts) > ROUTE_TTL_SECONDS

    def route(self, text: str, rag_hit: bool = False) -> str:
        """返回 LIGHTWEIGHT / RAG / HERMES。

        规则（Spec §3 四步 + ISSUE-0010 会话记忆 + 能力询问/礼貌语识别）：
        0. 能力询问（能不能/能否/会不会）→ LIGHTWEIGHT；礼貌/结束语 → LIGHTWEIGHT
        1. 命中技能/工具需求关键词 → HERMES（慢路径，先安抚）
        2. 命中知识库索引（rag_hit=True）→ RAG
        3. 上轮慢路径（未过 TTL）+ 本轮指代追问 → HERMES（延续慢路径，防跌回轻量编造）
        4. 其余 → LIGHTWEIGHT
        （兜底：轻量失败降级慢路径，在 pipeline 层处理，不在此处）
        """
        # 能力询问优先：问「能不能/能否」→ 快路径直接答，不触发工具、不发安抚语
        if self._is_capability_ask(text):
            logger.info("route=lightweight (capability ask: %s)", text)
            self._set_last_route(LIGHTWEIGHT)
            return LIGHTWEIGHT
        # 礼貌/结束语（谢谢/再见/晚安…）→ 快路径，不延续慢路径
        if self._is_polite(text):
            logger.info("route=lightweight (polite: %s)", text)
            self._set_last_route(LIGHTWEIGHT)
            return LIGHTWEIGHT
        for kw in self.skill_keywords:
            if kw and kw in text:
                logger.info("route=hermes (skill keyword: %s)", kw)
                self._set_last_route(HERMES)
                return HERMES
        for kw in self.tool_keywords:
            if kw and kw in text:
                logger.info("route=hermes (tool keyword: %s)", kw)
                self._set_last_route(HERMES)
                return HERMES
        if rag_hit:
            logger.info("route=rag")
            self._set_last_route(RAG)
            return RAG
        # ISSUE-0010：上轮慢路径（未过 TTL）+ 本轮指代追问 → 延续慢路径
        if self._last_route == HERMES and not self._route_memory_expired() and self._is_followup(text):
            logger.info("route=hermes (会话记忆：指代追问延续慢路径)")
            return HERMES
        self._set_last_route(LIGHTWEIGHT)
        logger.info("route=lightweight")
        return LIGHTWEIGHT

    def _is_polite(self, text: str) -> bool:
        """礼貌/结束语（谢谢/再见/晚安…）：不是追问，直接快路径。"""
        return any(w in text for w in POLITE_WHITELIST)

    def _is_capability_ask(self, text: str) -> bool:
        """能力询问：问系统「能不能/能否/会不会」做某事（如「你能不能查天气」）。

        与「查询命令」（帮我查天气）区分——能力询问不触发工具，直接回答能/不能。
        """
        # 含祈使/请求词 → 是命令（如「能帮我查吗」），不是能力询问
        for w in IMPERATIVE_HINTS:
            if w in text:
                return False
        return any(h in text for h in CAPABILITY_HINTS)

    def _is_followup(self, text: str) -> bool:
        """短句且是「上一轮的延续」而非「全新话题」。

        判定：① 含明确追问词 → 延续；② 否则短句且不含新话题信号 → 延续
        （ASR 常丢「呢」等轻声词，故用反向信号兜底）。
        """
        if len(text) > 10:
            return False
        if any(h in text for h in FOLLOWUP_HINTS):
            return True
        return not any(s in text for s in NEW_TOPIC_SIGNALS)

    def reset(self) -> None:
        """清空会话级路由记忆（测试/手动重置用）。"""
        self._last_route = None
        self._last_route_ts = 0.0
