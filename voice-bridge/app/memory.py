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

    def add_fact(self, category: str, fact: str) -> bool:
        """追加一条记忆（去重），返回是否真的新增。

        去重：事实文本已出现在任一条目（或反之）则跳过，避免重复积累。
        裁剪：超 MAX_FACTS 条裁最旧；超 MAX_BYTES 字节裁最旧（简单按条裁）。
        """
        fact = fact.strip()
        if not fact:
            return False
        entry = f"{time.strftime('%Y-%m-%d')} | {category.strip() or 'general'} | {fact}"
        with self._lock:
            facts = self.get_facts()
            for existing in facts:
                if fact in existing or existing in fact:
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
