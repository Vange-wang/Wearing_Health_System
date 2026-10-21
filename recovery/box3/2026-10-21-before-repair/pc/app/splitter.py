"""句子分割器 SentenceBuffer（Spec §6.2 + v0.4 A6 小数点消歧）。

接收 LLM 流式字符，按标点/长度触发分句；流结束时 flush 剩余内容。
A6：英文句点 "." 可作为句子终结标点，但「数字.数字」视为小数点不拆句（延迟判定）。
"""
import logging
import re

logger = logging.getLogger("voice-bridge.splitter")

# 中日英共用句子终结标点（Spec §6.2：。！？〜；\n）
# 含 ～(U+FF5E 全角波浪号)：LLM 实际输出此码位，与 〜(U+301C) 不同，两者都收（Hermes 查证 #2）
# 含 …(U+2026 省略号)：实测「揪心了…要不要」出现在语义停顿处（Hermes 查证 #2 评估决定加）
# 不含 —(U+2014 破折号)：实测「比如——」是引出下文非边界，加会误拆
_SENTENCE_PUNCT = set("。！？!?〜～…；;\n")

# 兜底拆分的可接受软边界（max_chars 超长时优先在这些字符处断，避免词中腰斩）
_SOFT_BOUNDARY = set("，,、 \t")

# 英文句点（A6：可作句号，但需与小数点消歧）
_ENGLISH_PERIOD = "."

# 可朗读字符：字母/数字/下划线 + 中日韩汉字（用于"纯标点跳过"判定）
_SPEAKABLE = re.compile(r"[\w\u4e00-\u9fff]")

# TTS 前清理：剥离 LLM 输出的 markdown/富文本标记，避免 TTS 念出"星号星号"等
# 覆盖：**加粗** / *斜体* / `代码` / # 标题 / [链接](url) / > 引用 等
_MD_BOLD_ITALIC = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")   # **xx** / *xx* / ***xx***
_MD_INLINE_CODE = re.compile(r"`([^`\n]+?)`")               # `xx`
_MD_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)       # # 标题
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")             # [文字](url) → 文字
_MD_QUOTE = re.compile(r"^>\s?", re.MULTILINE)              # > 引用
_MD_LIST = re.compile(r"^[-*+]\s+", re.MULTILINE)           # - / * / + 列表
_MD_ASTERISK_LEFT = re.compile(r"\*")                       # 残留孤立星号


def clean_markdown(text: str) -> str:
    """剥离 markdown 标记，保留正文（供 TTS/分句前调用）。"""
    if not text:
        return text
    s = text
    s = _MD_BOLD_ITALIC.sub(r"\1", s)      # **加粗** → 加粗
    s = _MD_INLINE_CODE.sub(r"\1", s)      # `code` → code
    s = _MD_LINK.sub(r"\1", s)             # [文字](url) → 文字
    s = _MD_HEADING.sub("", s)             # # 标题 → 标题
    s = _MD_QUOTE.sub("", s)               # > 引用 → 引用
    s = _MD_LIST.sub("", s)                # - 列表 → 列表
    s = _MD_ASTERISK_LEFT.sub("", s)       # 残留 *（防漏网）
    return s.strip()


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
                out.extend(self._split_at_boundary())  # 兜底：对齐软边界，防词中腰斩
        return out

    def flush(self) -> list[str]:
        """流结束，输出剩余内容（即使无标点）。"""
        self._pending_dot = False
        return self._flush()

    def _split_at_boundary(self) -> list[str]:
        """max_chars 兜底拆分：优先在最近的可接受软边界（逗号/顿号/空格）处断。

        边界字符归前一句（保留逗号的收尾自然停顿）；找不到任何软边界才硬切（整句 flush）+ 日志。
        防「那|些」类词中腰斩（Hermes 查证 #3）。
        """
        buf = "".join(self._buf)
        for i in range(len(buf) - 1, 0, -1):  # 从后往前找最近的软边界（跳过 i=0，避免空头）
            if buf[i] in _SOFT_BOUNDARY:
                head = buf[: i + 1]
                tail = buf[i + 1 :]
                self._buf = list(tail)
                s = head.strip()
                if s and _SPEAKABLE.search(s):
                    logger.debug("sentence (%d chars, soft-boundary split): %s", len(s), s[:40])
                    return [s]
                return []
        # 无软边界 → 硬切（整句 flush）+ 日志
        logger.warning("分句兜底硬切（%d chars 无软边界）: %s", len(buf), buf[:40])
        return self._flush()

    def _flush(self) -> list[str]:
        if not self._buf:
            return []
        s = "".join(self._buf).strip()
        self._buf = []
        s = clean_markdown(s)  # 句子组装完成后再清一次（覆盖跨 chunk 的 ** 标记）
        if not s or not _SPEAKABLE.search(s):
            return []  # 纯标点/空白跳过（Spec §6.2 空句子）
        logger.debug("sentence (%d chars): %s", len(s), s[:40])
        return [s]
