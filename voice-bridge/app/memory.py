"""语音长期记忆模块（需求 3，Spec §3.3）。

三层闭环：
- 持久层：`memory/user_facts.md`（§ 分隔条目，去重 + 裁剪），独立于 Hermes USER.md（不越权写）。
- 提取层：见 llm.py 的 LightweightLLM.extract_memory（调 DeepSeek 提取 REMEMBER 行）。
- 注入层：见 llm.py 的 LightweightLLM._system_prompt（追加 user_facts.md 内容）。

本模块只负责文件读写（线程安全），提取/注入在 llm.py。
"""
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("voice-bridge.memory")

MAX_FACTS = 100
MAX_BYTES = 8 * 1024  # 8KB（Spec §3.3 上限）


class MemoryStore:
    """语音记忆文件读写：`<日期> | <类别> | <事实>`，每行一条。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> str:
        """读取记忆文件内容（不存在/失败返回空串，不影响启动）。"""
        try:
            if not self.path.exists():
                return ""
            return self.path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def get_facts(self) -> list[str]:
        """返回所有条目（每行一条，过滤空行和注释行）。"""
        content = self.load()
        if not content:
            return []
        return [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def add_fact(self, category: str, fact: str, keywords: list[str] | None = None) -> bool:
        """追加一条记忆（去重），返回是否真的新增。

        去重（方案 B，Hermes 裁决）：
        - 子串匹配兜底（旧条目/无关键词场景）；
        - 关键词重叠度：交集/较小集 ≥ 阈值判重（<3 个关键词阈值 0.8，≥3 个阈值 0.6）。
        裁剪：超 MAX_FACTS 条裁最旧；超 MAX_BYTES 字节裁最旧（简单按条裁）。
        """
        fact = fact.strip()
        if not fact:
            return False
        kws = [k.strip() for k in (keywords or []) if k and k.strip()]
        entry = f"{time.strftime('%Y-%m-%d')} | {category.strip() or 'general'} | {fact}"
        if kws:
            entry += " | " + ",".join(kws)
        with self._lock:
            facts = self.get_facts()
            for existing in facts:
                # 子串匹配兜底
                existing_fact = self._extract_fact(existing)
                if fact in existing_fact or existing_fact in fact:
                    return False
                # 关键词重叠度判重（仅当新条目有关键词时）
                if kws:
                    existing_kws = self._extract_keywords(existing)
                    if existing_kws and self._overlap(kws, existing_kws):
                        return False
            facts.append(entry)
            if len(facts) > MAX_FACTS:
                facts = facts[-MAX_FACTS:]
            # 字节上限：从最旧开始裁，直到 ≤ MAX_BYTES
            content = "\n".join(facts)
            while len(content.encode("utf-8")) > MAX_BYTES and len(facts) > 1:
                facts = facts[1:]
                content = "\n".join(facts)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.warning("记忆写入失败: %s", e)
                return False
        return True

    @staticmethod
    def _extract_fact(entry: str) -> str:
        """从四段条目（日期|类别|事实|关键词）提取事实段；兼容旧三段条目。"""
        parts = entry.split("|")
        return parts[2].strip() if len(parts) >= 3 else entry.strip()

    @staticmethod
    def _extract_keywords(entry: str) -> list[str]:
        """从四段条目提取关键词列表；旧三段条目返回空。"""
        parts = entry.split("|")
        if len(parts) < 4:
            return []
        return [k.strip() for k in parts[3].split(",") if k.strip()]

    @staticmethod
    def _overlap(a: list[str], b: list[str]) -> bool:
        """关键词重叠度判重：交集/较小集合 ≥ 阈值。

        Hermes 修正①：<3 个关键词阈值 0.8（小集合 0.6 太松易误杀），≥3 个保持 0.6。
        """
        sa, sb = set(a), set(b)
        if not sa or not sb:
            return False
        inter = len(sa & sb)
        smaller = min(len(sa), len(sb))
        if smaller < 3:
            return inter / smaller >= 0.8
        return inter / smaller >= 0.6

    def remove_by_keyword(self, keyword: str) -> int:
        """按关键词删除条目（遗忘指令「忘掉我叫什么」），返回删除数。"""
        keyword = keyword.strip()
        if not keyword:
            return 0
        with self._lock:
            facts = self.get_facts()
            kept = [f for f in facts if keyword not in f]
            removed = len(facts) - len(kept)
            if removed:
                try:
                    self.path.write_text("\n".join(kept), encoding="utf-8")
                except Exception as e:
                    logger.warning("记忆删除写入失败: %s", e)
                    return 0
        return removed
