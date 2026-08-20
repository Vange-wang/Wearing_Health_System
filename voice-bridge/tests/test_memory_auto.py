"""需求3 记忆全自动改造单测：全自动触发 + FORGET 遗忘分支。

不依赖真实 DeepSeek API，mock client 返回指定提取结果，验证 memory 读写正确。
"""
import threading

from app.llm import LightweightLLM
from app.memory import MemoryStore


def _make_llm(tmp_path, memory_store=None):
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    llm = LightweightLLM("k", "http://127.0.0.1:1", "m", str(profile), memory_store=memory_store)
    return llm


def _fake_extract_resp(text):
    resp = type("Resp", (), {})()
    resp.choices = [type("Choice", (), {})()]
    resp.choices[0].message = type("Msg", (), {})()
    resp.choices[0].message.content = text
    return resp


def test_forget_removes_matching_facts(tmp_path):
    """FORGET: <关键词> 应调用 remove_by_keyword 删除对应条目。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    store.add_fact("possession", "单车是捷安特")
    store.add_fact("identity", "英文名 Vange")
    assert len(store.get_facts()) == 2

    llm = _make_llm(tmp_path, memory_store=store)
    # mock：提取结果只有 FORGET 分支（用户说「忘掉我的单车」）
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("FORGET: 单车")
    llm._extract_memory_sync("忘掉我的单车", "好的，已经忘记了。")

    facts = store.get_facts()
    assert len(facts) == 1
    assert "英文名 Vange" in facts[0]


def test_remember_adds_without_signal_word(tmp_path):
    """全自动提取：无信号词也照常新增（改造前会漏，见任务单现状1）。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    llm = _make_llm(tmp_path, memory_store=store)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("REMEMBER: possession: 单车是捷安特")
    # 「单车是捷安特」不含 MEMORY_SIGNAL_WORDS，但改造后仍应提取
    llm._extract_memory_sync("我的单车是捷安特", "好车！")
    assert "捷安特" in store.load()


def test_none_output_noop(tmp_path):
    """NONE → 不写任何条目。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    llm = _make_llm(tmp_path, memory_store=store)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("NONE")
    llm._extract_memory_sync("你好", "你好呀")
    assert store.load() == ""


def test_extract_memory_async_runs_without_signal_word(tmp_path):
    """extract_memory_async 每轮必做（不再看信号词），后台线程执行。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    llm = _make_llm(tmp_path, memory_store=store)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("REMEMBER: identity: 英文名 Vange")
    # 「随便聊聊」无信号词，但改造后 extract_memory_async 无条件触发
    llm.extract_memory_async("随便聊聊", "哈哈")
    # 等待后台线程完成
    deadline = 2.0
    import time
    t0 = time.time()
    while time.time() - t0 < deadline and "Vange" not in store.load():
        time.sleep(0.05)
    assert "Vange" in store.load()


def test_remember_and_forget_combined(tmp_path):
    """同一轮输出既有 REMEMBER 又有 FORGET：新增保留、遗忘删除。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    store.add_fact("possession", "单车是旧款")
    llm = _make_llm(tmp_path, memory_store=store)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp(
        "REMEMBER: possession: 单车是捷安特\nFORGET: 旧款"
    )
    llm._extract_memory_sync("我的单车换成捷安特了", "好的")
    facts = store.get_facts()
    assert any("捷安特" in f for f in facts)
    assert not any("旧款" in f for f in facts)
