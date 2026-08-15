"""知识库加载与热重载（长期 RAG，Spec §4 A4）。

- 扫描 `knowledge/*.md`，每个文件 = 一条知识（首行标题，其余正文）。
- 启动建索引；`reload()` 热重载。
"""
import logging
import threading
from pathlib import Path

from .rag import BM25Index

logger = logging.getLogger("voice-bridge.knowledge")


def _load_docs(knowledge_dir: Path) -> list[dict]:
    docs: list[dict] = []
    if not knowledge_dir.exists():
        return docs
    for f in sorted(knowledge_dir.glob("*.md")):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.warning("知识文件读取失败 %s: %s", f, e)
            continue
        # 跳过 YAML frontmatter / 纯标题空文
        title = ""
        body_lines = []
        started = False
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("---"):
                continue
            if not started and (s.startswith("#") or title == ""):
                title = s.lstrip("#").strip() or title
                if not s.startswith("#"):
                    body_lines.append(s)
                started = True
                continue
            body_lines.append(s)
        text = "\n".join(body_lines).strip()
        if not text:
            text = title
        if not title and not text:
            continue
        docs.append({"id": f.stem, "title": title or f.stem, "text": text or title})
    return docs


class KnowledgeBase:
    """内存知识库：维护 BM25 索引，支持热重载（线程安全）。"""

    def __init__(self, knowledge_dir: Path):
        self.knowledge_dir = Path(knowledge_dir)
        self._lock = threading.Lock()
        self._index: BM25Index = BM25Index([])
        self.reload()

    def reload(self) -> int:
        """重新扫描 knowledge/ 目录，返回加载条数。"""
        docs = _load_docs(self.knowledge_dir)
        with self._lock:
            self._index = BM25Index(docs)
        logger.info("知识库重载：%d 条", len(docs))
        return len(docs)

    def search(self, query: str, top_k: int = 3, score_threshold: float = 0.0) -> list[dict]:
        with self._lock:
            results = self._index.search(query, top_k=top_k)
        return [r for r in results if r["score"] >= score_threshold]

    def doc_count(self) -> int:
        with self._lock:
            return self._index._n
