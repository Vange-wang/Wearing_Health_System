"""ISSUE-0008 多轮指代消解测试。

轻量通道（DeepSeek）加滑动窗口会话历史，验证 chat/stream_chat 的 messages 携带历史。
"""
from app.llm import LightweightLLM


def _make_llm(tmp_path):
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    llm = LightweightLLM("k", "http://127.0.0.1:1", "m", str(profile))
    return llm


def _fake_resp(text):
    resp = type("Resp", (), {})()
    resp.choices = [type("Choice", (), {})()]
    resp.choices[0].message = type("Msg", (), {})()
    resp.choices[0].message.content = text
    return resp


def test_chat_history_injected(tmp_path):
    """连续两轮 chat，第二轮 messages 应包含第一轮的历史（user + assistant）。"""
    llm = _make_llm(tmp_path)
    captured = []

    def fake_create(**kwargs):
        captured.append(kwargs["messages"])
        return _fake_resp(f"第{len(captured)}轮回复")

    llm.client.chat.completions.create = fake_create

    llm.chat("广州天气怎么样")
    llm.chat("那深圳呢")

    msgs2 = captured[1]
    roles = [m["role"] for m in msgs2]
    contents = [m["content"] for m in msgs2]

    assert msgs2[0]["role"] == "system"
    assert roles.count("user") == 2        # 历史 user + 当前 user
    assert roles.count("assistant") == 1   # 历史 assistant
    assert contents[-1] == "那深圳呢"       # 当前 user 在最后
    assert "广州天气怎么样" in contents       # 历史 user 保留
    assert "第1轮回复" in contents           # 历史 assistant 保留


def test_stream_history_recorded(tmp_path):
    """流式 stream_chat 结束后，本轮对话应被记入历史。"""
    llm = _make_llm(tmp_path)
    captured = []

    def fake_stream_create(**kwargs):
        captured.append(kwargs["messages"])

        def chunks():
            c = type("Chunk", (), {})()
            c.choices = [type("Choice", (), {})()]
            c.choices[0].delta = type("Delta", (), {})()
            c.choices[0].delta.content = "流式回复"
            yield c

        return chunks()

    llm.client.chat.completions.create = fake_stream_create

    gen = llm.stream_chat("今天适合骑车吗")
    out = "".join(gen)  # 消费完流，触发 _remember

    assert out == "流式回复"
    assert len(llm._history) == 2  # 本轮 user + assistant 已记录


def test_session_ttl_clears_history(tmp_path):
    """超过 SESSION_TTL_SECONDS 无交互，历史应被清空（避免久远串上下文）。"""
    import time

    llm = _make_llm(tmp_path)
    llm._last_active = time.time() - 99999  # 模拟很久没交互
    captured = []

    def fake_create(**kwargs):
        captured.append(kwargs["messages"])
        return _fake_resp("回复")

    llm.client.chat.completions.create = fake_create
    llm.chat("现在问个新问题")

    msgs = captured[0]
    roles = [m["role"] for m in msgs]
    assert roles.count("user") == 1        # 只有当前 user，历史已清空
    assert roles.count("assistant") == 0
