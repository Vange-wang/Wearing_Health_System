"""分句器 SentenceBuffer 单测（句间连读修复 Spec T1/T2）。

T1：波浪号 ～(U+FF5E) 正确拆句（LLM 实际输出码位，与 〜(U+301C) 不同）。
T2：max_chars 兜底在最近逗号/顿号/空格处断，无词中腰斩。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.splitter import SentenceBuffer


def _split(text, max_chars=50):
    sb = SentenceBuffer(max_chars=max_chars)
    out = []
    for ch in text:
        out.extend(sb.feed(ch))
    out.extend(sb.flush())
    return out


def test_wave_dash_ff5e_splits():
    """T1：全角波浪号 ～(U+FF5E) 应拆句（LLM 实际输出码位）。"""
    r = _split("但熬夜调试确实辛苦啦～今晚早点休息，健康最重要！")
    assert len(r) == 2
    assert r[0] == "但熬夜调试确实辛苦啦～"
    assert r[1] == "今晚早点休息，健康最重要！"


def test_wave_dash_u301c_also_splits():
    """原分句集的 〜(U+301C) 仍应拆句（向后兼容）。"""
    r = _split("辛苦啦〜早点休息")
    assert len(r) == 2


def test_ellipsis_splits():
    """省略号 …(U+2026) 在语义停顿处拆句。"""
    r = _split("听你这么说我也跟着揪心了…要不要跟我念叨念叨？")
    assert len(r) == 2


def test_max_chars_splits_at_comma():
    """T2：超长兜底在最近逗号处断，无词中腰斩。"""
    text = (
        "长期熬夜对身体伤害很大，生物钟会乱，免疫力也会下降，"
        "心脏和免疫系统最遭罪，黑眼圈注意力差都是小事，真的要注意身体啊"
    )
    r = _split(text, max_chars=30)
    assert len(r) >= 3
    # 每句都应落在逗号处（逗号归前一句），且没有明显词中腰斩
    for s in r[:-1]:  # 除最后一句（flush 剩余），都应以逗号结尾
        assert s.endswith("，")
    assert r[-1] == "真的要注意身体啊"


def test_comma_not_split_short_sentence():
    """逗号本身不拆短句（逗号是软边界，只在兜底时用）。"""
    r = _split("哈哈，你好呀～")
    assert len(r) == 1  # 波浪号前只有一个逗号，整句不拆（波浪号才拆）
