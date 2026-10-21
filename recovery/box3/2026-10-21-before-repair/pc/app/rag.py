"""BM25 关键词检索（长期 RAG，Spec §4 A3：零重依赖起步）。

- jieba 分词 + 自实现 BM25，numpy 向量化打分，top-k 召回。
- 无语义（"胸口疼"↛"胸痛"），起步接受；语义增强 bge-onnx 留后续单独立项。
"""
import logging
import math
from typing import Iterable

import numpy as np

logger = logging.getLogger("voice-bridge.rag")

# BM25 参数（标准默认）
_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    """中文分词（jieba，纯 Python）。"""
    import jieba

    return [w for w in jieba.lcut(text) if w.strip()]


class BM25Index:
    """内存 BM25 索引：docs = [{"id","title","text"}, ...]。"""

    def __init__(self, docs: list[dict]):
        self.docs = docs
        self._build(docs)

    def _build(self, docs: list[dict]):
        self._tokens: list[list[str]] = []
        self._doc_lens: list[int] = []
        for d in docs:
            title = d.get("title", "")
            toks = tokenize(f"{title}\n{d.get('text', '')}")
            self._tokens.append(toks)
            self._doc_lens.append(len(toks))
        self._avg_dl = float(np.mean(self._doc_lens)) if self._doc_lens else 1.0
        self._df: dict[str, int] = {}
        for toks in self._tokens:
            for w in set(toks):
                self._df[w] = self._df.get(w, 0) + 1
        self._n = len(docs)
        self._idf = {
            w: math.log(1 + (self._n - df + 0.5) / (df + 0.5))
            for w, df in self._df.items()
        }

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """返回 top_k 条命中：[{doc, score}]，按分数降序。"""
        if self._n == 0:
            return []
        qtoks = tokenize(query)
        scores = np.zeros(self._n, dtype=np.float64)
        for w in set(qtoks):
            idf = self._idf.get(w)
            if idf is None:
                continue
            for i, toks in enumerate(self._tokens):
                if not toks:
                    continue
                tf = toks.count(w)
                denom = tf + _K1 * (1 - _B + _B * (self._doc_lens[i] / self._avg_dl))
                scores[i] += idf * (tf * (_K1 + 1)) / denom
        order = np.argsort(scores)[::-1][:top_k]
        results = []
        for i in order:
            if scores[i] <= 0:
                continue
            results.append({"doc": self.docs[i], "score": float(scores[i])})
        return results
