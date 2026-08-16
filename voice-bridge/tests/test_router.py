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
        tool_keywords=["查快递", "写文件", "发邮件", "定时", "搜网页", "搜索", "查天气", "帮我查"],
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
