"""路由判定单测（ISSUE-0010 会话级路由记忆 + 能力询问 + 礼貌语 + TTL）。

Hermes 第 1 轮审查 NON_SERIOUS 建议 #1：路由记忆无独立单测，补 test_router.py。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.router import Router, LIGHTWEIGHT, HERMES


def _router():
    return Router(
        tool_keywords=["查快递", "写文件", "发邮件", "定时", "搜网页", "搜索", "查天气", "帮我查",
                       "查一下", "查查", "查下", "看一下", "看看", "看下", "找一下", "找找", "找下",
                       "怎么样", "的情况", "如何", "好不好", "是什么", "了解下", "介绍下"],
        skill_keywords=[],
    )


def test_tool_keyword_routes_hermes():
    r = _router()
    assert r.route("帮我查一下天气") == HERMES
    assert r.route("查天气") == HERMES


def test_followup_continues_slow_path():
    """上轮慢路径 + 本轮指代追问 → 延续慢路径（防跌回轻量编造）。"""
    r = _router()
    assert r.route("帮我查一下东莞天气") == HERMES
    assert r.route("深圳的呢") == HERMES  # 指代追问延续
    assert r.route("那广州呢") == HERMES  # 继续追问


def test_polite_phrase_breaks_followup():
    """礼貌/结束语 → 快路径，不延续慢路径（「慢路径后说谢谢」不误判追问）。"""
    r = _router()
    r.route("帮我查一下天气")
    assert r.route("谢谢") == LIGHTWEIGHT
    assert r.route("晚安") == LIGHTWEIGHT


def test_capability_ask_routes_lightweight():
    """能力询问（能不能/能否/你能）→ 快路径直答，不触发工具。"""
    r = _router()
    assert r.route("你能不能查天气") == LIGHTWEIGHT
    assert r.route("能否查天气") == LIGHTWEIGHT
    assert r.route("你会查天气吗") == LIGHTWEIGHT


def test_imperative_phrase_is_not_capability_ask():
    """含祈使词（帮我/请你）→ 命令而非能力询问，走慢路径。"""
    r = _router()
    assert r.route("能帮我查天气吗") == HERMES
    assert r.route("帮我查天气") == HERMES


def test_route_memory_expires_after_ttl():
    """上一轮路由记忆过 TTL（600s）后不延续慢路径。"""
    r = _router()
    r.route("帮我查天气")  # hermes
    r._last_route_ts = time.monotonic() - 700  # 模拟 700s 前
    assert r.route("深圳的呢") == LIGHTWEIGHT  # 过 TTL，不延续


def test_new_topic_breaks_followup():
    """全新话题（含新话题信号）不延续慢路径。"""
    r = _router()
    r.route("帮我查天气")
    assert r.route("讲个笑话") == LIGHTWEIGHT  # 新话题信号「讲」


def test_imperative_word_family_routes_hermes():
    """祈使词族（查一下/看一下/找一下）→ 慢路径，不受长度限制。"""
    r = _router()
    assert r.route("查一下广东医科大学") == HERMES
    assert r.route("看一下今天天气") == HERMES
    assert r.route("找一下快递") == HERMES


def test_broad_word_long_entity_query_routes_hermes():
    """宽词（怎么样/的情况）命中 + 句长 ≥5 → 实体查询走慢路径。"""
    r = _router()
    assert r.route("广东医科大学怎么样") == HERMES
    assert r.route("东莞今天天气的情况") == HERMES


def test_broad_word_short_chat_stays_lightweight():
    """宽词命中但句长 <5（单说「怎么样？」）→ 退回原逻辑，不误走慢路径。"""
    r = _router()
    assert r.route("怎么样") == LIGHTWEIGHT
    assert r.route("是什么") == LIGHTWEIGHT


def test_classify_followup_recognizes_exact_replay_phrases():
    """仅完整复述短语进入 REPLAY，不复用 ISSUE-0010 的宽松追问判定。"""
    r = _router()
    replay_phrases = (
        "重新说一遍", "再说一遍", "重复一遍", "重新说一次",
        "再说一次", "重复一次", "再来一遍", "重新播一遍",
    )
    for text in replay_phrases:
        assert r.classify_followup(text) == "replay"


def test_classify_followup_recognizes_context_phrases():
    """明确的上一轮指代进入 CONTEXT。"""
    r = _router()
    context_phrases = (
        "刚才那个", "刚才说的", "那个呢", "那这个呢",
        "刚才那个呢", "刚才说的是什么",
    )
    for text in context_phrases:
        assert r.classify_followup(text) == "context"


def test_classify_followup_rejects_broad_single_token_false_positives():
    """普通命令、闲聊和单轮措辞不能被误判成跨轮联动。"""
    r = _router()
    for text in (
        "查询一次天气", "说一遍注意事项", "再查一次天气",
        "说一下天气", "讲个笑话", "谢谢",
    ):
        assert r.classify_followup(text) is None
