"""路由判定（长期 RAG，Spec §3 A2 四步规则）。

默认轻量（快），命中技能/工具需求走慢路径，命中知识库走 RAG。
ISSUE-0010：会话级路由记忆——上轮慢路径（查天气等）时，本轮指代追问
（「深圳的呢」）延续慢路径，避免跌回轻量通道 DeepSeek 裸模型编造实时数据。
"""
import logging
import time

logger = logging.getLogger("voice-bridge.router")

# 路由结果（+ DATA：健康数据查询，BLE 立项 Spec §4.1，优先级高于 RAG）
LIGHTWEIGHT = "lightweight"
RAG = "rag"
HERMES = "hermes"
DATA = "data"

# 会话级路由记忆 TTL（对齐 LLM 历史 600s 过期；超时不再延续上一轮慢路径）
ROUTE_TTL_SECONDS = 600

# 指代/追问提示词：短句含这些词 → 视为上一轮的延续（而非全新话题）
FOLLOWUP_HINTS = ["呢", "那", "它", "这", "也", "还有", "多少", "几度", "几点", "再"]

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

# 宽词（描述性疑问词）：「XX怎么样/是什么/的情况」类实体查询会命中，但短句闲聊
# （单说「怎么样？」「是什么？」）也会命中 → 需加长度校验（阶段2），避免误走慢路径。
BROAD_QUERY_WORDS = ["怎么样", "是什么", "的情况", "如何", "好不好", "了解下", "介绍下"]

# 宽词命中判 HERMES 的最小句长（< 此值视为闲聊/指代，退回原逻辑）
BROAD_QUERY_MIN_LEN = 5


class Router:
    def __init__(self, tool_keywords: list[str], skill_keywords: list[str],
                 data_keywords: list[str] | None = None,
                 asr_normalize: dict[str, str] | None = None):
        self.tool_keywords = [k for k in tool_keywords if k]
        self.skill_keywords = [k for k in skill_keywords if k]
        self.data_keywords = [k for k in (data_keywords or []) if k]
        # ASR 近音词归一（如 血阳/学养/学样 → 血氧），路由前应用
        self.asr_normalize = {k: v for k, v in (asr_normalize or {}).items() if k}
        # ISSUE-0010：上一轮路由（会话级记忆；单设备够用，多设备需按来源区分）
        self._last_route: str | None = None
        self._last_route_ts: float = 0.0  # _last_route 设置时刻（monotonic），用于 TTL 过期

    def normalize_asr(self, text: str) -> str:
        """ASR 近音词归一（路由前调用）：血氧的同音误识别（血阳/学养/学样）归一为血氧。
        血压语义不同，不在归一表内。"""
        for wrong, right in self.asr_normalize.items():
            if wrong in text:
                text = text.replace(wrong, right)
        return text

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

        规则（Spec §3 四步 + ISSUE-0010 会话记忆 + 能力询问/礼貌语识别 + DATA）：
        0. 能力询问（能不能/能否/会不会）→ LIGHTWEIGHT；礼貌/结束语 → LIGHTWEIGHT
        1. 命中技能/工具需求关键词 → HERMES（慢路径，先安抚）
        2. 命中健康数据关键词（心率/血氧）→ DATA（模板直答，排在 RAG 前）
        3. 命中知识库索引（rag_hit=True）→ RAG
        4. 上轮慢路径（未过 TTL）+ 本轮指代追问 → HERMES（延续慢路径，防跌回轻量编造）
        5. 其余 → LIGHTWEIGHT
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
        # DATA 路由（BLE 立项 Spec §4.1 + 2026-08-23 路由顺序修正）：
        # 心率/血氧核心词 → 健康数据模板直答。排在祈使词族（查一下/看一下）之前——
        # 「帮我查一下血氧」意图是查数据而非搜索；排在 RAG 前防截胡。
        for kw in self.data_keywords:
            if kw and kw in text:
                logger.info("route=data (health data keyword: %s)", kw)
                self._set_last_route(DATA)
                return DATA
        if rag_hit:
            logger.info("route=rag")
            self._set_last_route(RAG)
            return RAG
        # 指代追问延续（ISSUE-0010 + 2026-08-23 DATA 延续）：排在工具词之前——
        # 「你再看一下」含工具词「看一下」，但意图是延续上轮数据查询；
        # HERMES 延续与工具词命中目的地相同，前置无副作用。RAG 保持在其前
        # （知识查询优先于追问延续，test_t2_router 约束）。
        if not self._route_memory_expired() and self._is_followup(text):
            if self._last_route == HERMES:
                logger.info("route=hermes (会话记忆：指代追问延续慢路径)")
                return HERMES
            if self._last_route == DATA:
                logger.info("route=data (会话记忆：指代追问延续数据查询)")
                return DATA
        for kw in self.skill_keywords:
            if kw and kw in text:
                logger.info("route=hermes (skill keyword: %s)", kw)
                self._set_last_route(HERMES)
                return HERMES
        for kw in self.tool_keywords:
            if kw and kw in text:
                # 阶段2：宽词（怎么样/是什么/的情况/如何/好不好/了解下/介绍下）命中时，
                # 需句长 ≥ BROAD_QUERY_MIN_LEN 才视为实体查询走慢路径；短句闲聊退回原逻辑。
                # 祈使词族（查一下/看一下/找一下 等）不受长度限制，直接走慢路径。
                if kw in BROAD_QUERY_WORDS and len(text) < BROAD_QUERY_MIN_LEN:
                    logger.info("route 宽词命中但句长过短（%d 字），退回原逻辑: %s", len(text), kw)
                    continue
                logger.info("route=hermes (tool keyword: %s)", kw)
                self._set_last_route(HERMES)
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
