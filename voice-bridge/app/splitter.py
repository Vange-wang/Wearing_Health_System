"""句子分割器 SentenceBuffer（Spec §6.2 + v0.4 A6 小数点消歧）。

接收 LLM 流式字符，按标点/长度触发分句；流结束时 flush 剩余内容。
A6：英文句点 "." 可作为句子终结标点，但「数字.数字」视为小数点不拆句（延迟判定）。
"""
import logging
import re

logger = logging.getLogger("voice-bridge.splitter")

# 中日英共用句子终结标点（Spec §6.2：。！？〜；\n）
_SENTENCE_PUNCT = set("。！？!?〜；;\n")

# 英文句点（A6：可作句号，但需与小数点消歧）
_ENGLISH_PERIOD = "."

# 可朗读字符：字母/数字/下划线 + 中日韩汉字（用于"纯标点跳过"判定）
_SPEAKABLE = re.compile(r"[\w\u4e00-\u9fff]")


class SentenceBuffer:
    """流式字符 → 完整句子列表。

    触发条件（任一满足即输出当前 buffered 文本为一句）：
    1. 遇到标点（。！？〜；\\n）
    2. 遇到英文句点 "."（A6，且非小数点——数字.数字 不拆）
    3. 缓冲区长度 ≥ max_chars（长句保护）
    4. 显式 flush()（LLM 流结束）
    连续标点合并为一次分割；纯标点/空白句子跳过。
    """

    def __init__(self, max_chars: int = 50):
        self.max_chars = int(max_chars)
        self._buf: list[str] = []
        self._pending_dot = False  # 上一个字符是 "."，等下一个字符判定小数点/句号

    def feed(self, text: str) -> list[str]:
        """喂入一段字符流，返回其中新产出的完整句子。"""
        out: list[str] = []
        for ch in text:
            # 判定上一个 "."：后面是数字→小数点（不拆）；否则→句号（拆）
            if self._pending_dot:
                self._pending_dot = False
                if not ch.isdigit():
                    out.extend(self._flush())
            self._buf.append(ch)
            if ch in _SENTENCE_PUNCT:
                out.extend(self._flush())
            elif ch == _ENGLISH_PERIOD:
                self._pending_dot = True  # 延迟到下一个字符判定
            elif len(self._buf) >= self.max_chars:
                out.extend(self._flush())
        return out

    def flush(self) -> list[str]:
        """流结束，输出剩余内容（即使无标点）。"""
        self._pending_dot = False
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
