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


# ---------------- 去重（方案B 关键词重叠度，Hermes 裁决） ----------------

def test_keyword_overlap_dedup_same_fact_different_wording(tmp_path):
    """同一事实不同措辞，关键词高度重叠 → 判重只记 1 条。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    # 第一次：单车是 FACTOR OSTRO VAM
    assert store.add_fact("物品", "单车是FACTOR OSTRO VAM", ["FACTOR", "OSTRO", "VAM", "单车"])
    # 第二次：措辞不同，但关键词重叠 4/4
    assert not store.add_fact("物品", "用户的自行车是FACTOR OSTRO VAM型号", ["FACTOR", "OSTRO", "VAM", "单车"])
    assert len(store.get_facts()) == 1


def test_keyword_overlap_dedup_partial_overlap(tmp_path):
    """关键词部分重叠（≥3 个时阈值 0.6）→ 判重。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    store.add_fact("物品", "单车是FACTOR OSTRO VAM", ["FACTOR", "OSTRO", "VAM", "单车"])
    # 关键词 3/4 重叠（FACTOR/OSTRO/VAM），阈值 0.6 → 判重
    assert not store.add_fact("物品", "单车品牌FACTOR型号OSTRO VAM", ["FACTOR", "OSTRO", "VAM"])
    assert len(store.get_facts()) == 1


def test_different_facts_not_deduped(tmp_path):
    """不同事实关键词不重叠 → 分别记录，不误杀。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    assert store.add_fact("物品", "单车是FACTOR OSTRO VAM", ["FACTOR", "OSTRO", "VAM", "单车"])
    assert store.add_fact("学校", "广东医科大学", ["广东医科大学", "大学"])
    assert len(store.get_facts()) == 2


def test_small_keyword_set_higher_threshold(tmp_path):
    """关键词 <3 个时阈值 0.8：2 个关键词重叠 1 个（0.5 < 0.8）不判重；全重叠（1.0）判重。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    # 2 个关键词完全重叠 → 判重
    assert store.add_fact("物品", "单车FACTOR", ["FACTOR", "单车"])
    assert not store.add_fact("物品", "单车就是FACTOR", ["FACTOR", "单车"])
    # 2 个关键词重叠 1 个（0.5 < 0.8）→ 不判重
    assert store.add_fact("物品", "单车Giant", ["Giant", "单车"])
    assert len(store.get_facts()) == 2


def test_empty_keywords_fallback_substring(tmp_path):
    """无关键词时退回子串匹配兜底。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    assert store.add_fact("物品", "单车是FACTOR", None)
    # 无关键词的新条目，靠子串匹配判重（旧逻辑）
    assert not store.add_fact("物品", "单车是FACTOR", None)
    assert len(store.get_facts()) == 1


def test_extract_parses_keywords(tmp_path):
    """提取层解析 REMEMBER ... ;; 关键词: 格式，把关键词传给 add_fact。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    llm = _make_llm(tmp_path, memory_store=store)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp(
        "REMEMBER: 物品: 单车是FACTOR OSTRO VAM ;; 关键词: FACTOR, OSTRO, VAM, 单车"
    )
    llm._extract_memory_sync("我的单车是FACTOR OSTRO VAM", "好车")
    facts = store.get_facts()
    assert len(facts) == 1
    assert "FACTOR" in facts[0] and "VAM" in facts[0]  # 关键词已写入四段格式


def test_extract_legacy_no_keywords(tmp_path):
    """提取层兼容旧格式（无关键词），仍能新增。"""
    store = MemoryStore(tmp_path / "user_facts.md")
    llm = _make_llm(tmp_path, memory_store=store)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("REMEMBER: 物品: 单车是FACTOR")
    llm._extract_memory_sync("我的单车是FACTOR", "好车")
    assert "FACTOR" in store.load()

