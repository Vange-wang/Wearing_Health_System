"""需求3 记忆单测（单一记忆源 v2）：全自动触发 + FORGET 遗忘 + 注入 + 客户端调用。

不依赖真实 DeepSeek API 和 memory_server，mock client 返回指定提取结果、
mock MemoryClient 记录调用，验证 llm.py 编排正确。
"""
import threading
import time

from app.llm import LightweightLLM


class _MockMemoryClient:
    """记录 add_fact / remove_by_keyword / load_recent 调用，返回可控结果。"""

    def __init__(self, recent: str = ""):
        self.recent = recent
        self.added = []        # (category, fact, keywords)
        self.removed = []      # [keyword, ...]
        self._add_return = True
        self._remove_return = 1

    def load_recent(self) -> str:
        return self.recent

    def add_fact(self, category, fact, keywords=None) -> bool:
        self.added.append((category, fact, keywords))
        return self._add_return

    def remove_by_keyword(self, keyword) -> int:
        self.removed.append(keyword)
        return self._remove_return


def _make_llm(tmp_path, memory=None):
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    llm = LightweightLLM("k", "http://127.0.0.1:1", "m", str(profile), memory_store=memory)
    return llm


def _fake_extract_resp(text):
    resp = type("Resp", (), {})()
    resp.choices = [type("Choice", (), {})()]
    resp.choices[0].message = type("Msg", (), {})()
    resp.choices[0].message.content = text
    return resp


def test_forget_calls_remove_by_keyword(tmp_path):
    """FORGET: <关键词> 应调用 memory.remove_by_keyword。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("FORGET: 英文名字")
    llm._extract_memory_sync("忘掉我的英文名", "好的。")
    assert mem.removed == ["英文名字"]


def test_remember_calls_add_fact(tmp_path):
    """全自动提取：无信号词也照常调 add_fact 写入。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("REMEMBER: 物品: 单车是FACTOR")
    llm._extract_memory_sync("我的单车是FACTOR", "好车！")
    assert len(mem.added) == 1
    assert mem.added[0][0] == "物品"
    assert "FACTOR" in mem.added[0][1]


def test_none_output_noop(tmp_path):
    """NONE → 不调 add_fact。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("NONE")
    llm._extract_memory_sync("你好", "你好呀")
    assert mem.added == []


def test_extract_memory_async_runs_without_signal_word(tmp_path):
    """extract_memory_async 每轮必做（不看信号词），后台线程执行。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("REMEMBER: identity: 英文名 Vange")
    llm.extract_memory_async("随便聊聊", "哈哈")
    deadline = 2.0
    t0 = time.time()
    while time.time() - t0 < deadline and not mem.added:
        time.sleep(0.05)
    assert len(mem.added) == 1


def test_remember_and_forget_combined(tmp_path):
    """同一轮既有 REMEMBER 又有 FORGET：新增 + 删除都调用。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp(
        "REMEMBER: 物品: 单车是捷安特\nFORGET: 旧款"
    )
    llm._extract_memory_sync("我的单车换成捷安特了", "好的")
    assert len(mem.added) == 1
    assert mem.removed == ["旧款"]


# ---------------- 注入（读）：load_recent ----------------

def test_system_prompt_injects_recent(tmp_path):
    """_system_prompt 注入 USER.md 全文 + MEMORY.md 最近窗口（load_recent）。"""
    mem = _MockMemoryClient(recent="用户的单车是FACTOR OSTRO VAM")
    llm = _make_llm(tmp_path, memory=mem)
    prompt = llm._system_prompt()
    assert "用户喜欢骑车" in prompt          # USER.md 画像注入
    assert "单车是FACTOR OSTRO VAM" in prompt  # MEMORY.md 最近窗口注入


def test_system_prompt_empty_recent_ok(tmp_path):
    """MEMORY.md 为空 → 静默跳过，不报错，仍注入 USER.md。"""
    mem = _MockMemoryClient(recent="")
    llm = _make_llm(tmp_path, memory=mem)
    prompt = llm._system_prompt()
    assert "用户喜欢骑车" in prompt


# ---------------- 提取解析关键词 ----------------

def test_extract_parses_keywords(tmp_path):
    """提取层解析 REMEMBER ... ;; 关键词: 格式，关键词传给 add_fact。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp(
        "REMEMBER: 物品: 单车是FACTOR OSTRO VAM ;; 关键词: FACTOR, OSTRO, VAM, 单车"
    )
    llm._extract_memory_sync("我的单车是FACTOR OSTRO VAM", "好车")
    assert len(mem.added) == 1
    cat, fact, kws = mem.added[0]
    assert cat == "物品"
    assert "FACTOR" in fact
    assert kws == ["FACTOR", "OSTRO", "VAM", "单车"]


def test_extract_legacy_no_keywords(tmp_path):
    """提取层兼容旧格式（无关键词），仍调 add_fact（keywords=None）。"""
    mem = _MockMemoryClient()
    llm = _make_llm(tmp_path, memory=mem)
    llm.client.chat.completions.create = lambda **kw: _fake_extract_resp("REMEMBER: 物品: 单车是FACTOR")
    llm._extract_memory_sync("我的单车是FACTOR", "好车")
    assert len(mem.added) == 1
    assert mem.added[0][2] is None
