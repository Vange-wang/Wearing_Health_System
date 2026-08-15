"""句子分割器 SentenceBuffer（Spec §6.2）。

接收 LLM 流式字符，按标点/长度触发分句；流结束时 flush 剩余内容。
"""
import logging
import re

logger = logging.getLogger("voice-bridge.splitter")

# 中日英共用句子终结标点（Spec §6.2：。！？〜；\n）
_SENTENCE_PUNCT = set("。！？!?〜；;\n")

# 可朗读字符：字母/数字/下划线 + 中日韩汉字（用于"纯标点跳过"判定）
_SPEAKABLE = re.compile(r"[\w\u4e00-\u9fff]")


class SentenceBuffer:
    """流式字符 → 完整句子列表。

    触发条件（任一满足即输出当前 buffered 文本为一句）：
    1. 遇到标点（。！？〜；\\n）
    2. 缓冲区长度 ≥ max_chars（长句保护）
    3. 显式 flush()（LLM 流结束）
    连续标点合并为一次分割；纯标点/空白句子跳过。
    """

    def __init__(self, max_chars: int = 50):
        self.max_chars = int(max_chars)
        self._buf: list[str] = []

    def feed(self, text: str) -> list[str]:
        """喂入一段字符流，返回其中新产出的完整句子。"""
        out: list[str] = []
        for ch in text:
            self._buf.append(ch)
            if ch in _SENTENCE_PUNCT:
                out.extend(self._flush())
            elif len(self._buf) >= self.max_chars:
                out.extend(self._flush())
        return out

    def flush(self) -> list[str]:
        """流结束，输出剩余内容（即使无标点）。"""
        return self._flush()

    def _flush(self) -> list[str]:
        if not self._buf:
            return []
        s = "".join(self._buf).strip()
        self._buf = []
        if not s or not _SPEAKABLE.search(s):
            return []  # 纯标点/空白跳过（Spec §6.2 空句子）
        logger.debug("sentence (%d chars): %s", len(s), s[:40])
        return [s]
