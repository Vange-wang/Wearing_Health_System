"""路由判定（长期 RAG，Spec §3 A2 四步规则）。

默认轻量（快），命中技能/工具需求走慢路径，命中知识库走 RAG。
"""
import logging

logger = logging.getLogger("voice-bridge.router")

# 三类路由结果
LIGHTWEIGHT = "lightweight"
RAG = "rag"
HERMES = "hermes"


class Router:
    def __init__(self, tool_keywords: list[str], skill_keywords: list[str]):
        self.tool_keywords = [k for k in tool_keywords if k]
        self.skill_keywords = [k for k in skill_keywords if k]

    def route(self, text: str, rag_hit: bool = False) -> str:
        """返回 LIGHTWEIGHT / RAG / HERMES。

        规则（Spec §3 四步）：
        1. 命中技能/工具需求关键词 → HERMES（慢路径，先安抚）
        2. 命中知识库索引（rag_hit=True）→ RAG
        3. 其余 → LIGHTWEIGHT
        （兜底：轻量失败降级慢路径，在 pipeline 层处理，不在此处）
        """
        for kw in self.skill_keywords:
            if kw and kw in text:
                logger.info("route=hermes (skill keyword: %s)", kw)
                return HERMES
        for kw in self.tool_keywords:
            if kw and kw in text:
                logger.info("route=hermes (tool keyword: %s)", kw)
                return HERMES
        if rag_hit:
            logger.info("route=rag")
            return RAG
        logger.info("route=lightweight")
        return LIGHTWEIGHT
