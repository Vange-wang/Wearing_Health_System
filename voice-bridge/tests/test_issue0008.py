"""ISSUE-0008 多轮指代消解测试。

轻量通道（DeepSeek）加滑动窗口会话历史，验证 chat/stream_chat 的 messages 携带历史。
"""
import json

from app.llm import ConversationHistory, HermesLLM, LightweightLLM


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


class _FakeHermesResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None

    def iter_lines(self):
        payload = {"choices": [{"delta": {"content": self.text}}]}
        yield "data: " + json.dumps(payload, ensure_ascii=False)
        yield "data: [DONE]"

    def close(self):
        return None


class _FakeHermesStreamClient:
    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    def build_request(self, method, url, json, headers):
        self.messages = json["messages"]
        return object()

    def send(self, request, stream):
        return _FakeHermesResponse(self.reply)


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


def test_history_is_shared_from_lightweight_to_hermes(tmp_path):
    """快路径完成的一轮，下一轮切到 Hermes 后仍必须携带。"""
    history = ConversationHistory()
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    lightweight = LightweightLLM(
        "k", "http://127.0.0.1:1", "m", str(profile),
        conversation_history=history,
    )
    hermes = HermesLLM(
        "k", "http://127.0.0.1:1/v1", "m",
        conversation_history=history,
    )
    captured = []

    lightweight.client.chat.completions.create = lambda **kwargs: _fake_resp("我记住了，你叫小王。")

    def fake_hermes_create(**kwargs):
        captured.append(kwargs["messages"])
        return _fake_resp("你好，小王。")

    hermes.client.chat.completions.create = fake_hermes_create
    lightweight.chat("我叫小王")
    hermes.chat("我叫什么")

    assert {"role": "user", "content": "我叫小王"} in captured[0]
    assert {"role": "assistant", "content": "我记住了，你叫小王。"} in captured[0]


def test_history_is_shared_from_hermes_to_lightweight(tmp_path):
    """慢路径完成的一轮，下一轮切回快路径后仍必须携带。"""
    history = ConversationHistory()
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    hermes = HermesLLM(
        "k", "http://127.0.0.1:1/v1", "m",
        conversation_history=history,
    )
    lightweight = LightweightLLM(
        "k", "http://127.0.0.1:1", "m", str(profile),
        conversation_history=history,
    )
    captured = []

    hermes.client.chat.completions.create = lambda **kwargs: _fake_resp("北京今天有雨。")

    def fake_lightweight_create(**kwargs):
        captured.append(kwargs["messages"])
        return _fake_resp("建议带伞。")

    lightweight.client.chat.completions.create = fake_lightweight_create
    hermes.chat("查一下北京天气")
    lightweight.chat("那要带伞吗")

    assert {"role": "user", "content": "查一下北京天气"} in captured[0]
    assert {"role": "assistant", "content": "北京今天有雨。"} in captured[0]


def test_stream_history_crosses_from_lightweight_to_hermes(tmp_path):
    """真机使用的 stream_chat 路径也必须从快路径跨到慢路径。"""
    history = ConversationHistory()
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    lightweight = LightweightLLM(
        "k", "http://127.0.0.1:1", "m", str(profile),
        conversation_history=history,
    )
    hermes = HermesLLM(
        "k", "http://127.0.0.1:1/v1", "m",
        conversation_history=history,
    )

    def fake_lightweight_stream(**kwargs):
        chunk = type("Chunk", (), {})()
        chunk.choices = [type("Choice", (), {})()]
        chunk.choices[0].delta = type("Delta", (), {"content": "我记住了。"})()
        return iter([chunk])

    lightweight.client.chat.completions.create = fake_lightweight_stream
    hermes_stream = _FakeHermesStreamClient("你的名字是小王。")
    hermes._stream_client = hermes_stream

    assert "".join(lightweight.stream_chat("我叫小王")) == "我记住了。"
    assert "".join(hermes.stream_chat("我叫什么")) == "你的名字是小王。"

    assert {"role": "user", "content": "我叫小王"} in hermes_stream.messages
    assert {"role": "assistant", "content": "我记住了。"} in hermes_stream.messages


def test_stream_history_crosses_from_hermes_to_lightweight(tmp_path):
    """真机使用的 stream_chat 路径也必须从慢路径跨回快路径。"""
    history = ConversationHistory()
    profile = tmp_path / "USER.md"
    profile.write_text("用户喜欢骑车。", encoding="utf-8")
    hermes = HermesLLM(
        "k", "http://127.0.0.1:1/v1", "m",
        conversation_history=history,
    )
    lightweight = LightweightLLM(
        "k", "http://127.0.0.1:1", "m", str(profile),
        conversation_history=history,
    )
    hermes._stream_client = _FakeHermesStreamClient("北京今天有雨。")
    captured = []

    def fake_lightweight_stream(**kwargs):
        captured.append(kwargs["messages"])
        chunk = type("Chunk", (), {})()
        chunk.choices = [type("Choice", (), {})()]
        chunk.choices[0].delta = type("Delta", (), {"content": "建议带伞。"})()
        return iter([chunk])

    lightweight.client.chat.completions.create = fake_lightweight_stream

    assert "".join(hermes.stream_chat("查一下北京天气")) == "北京今天有雨。"
    assert "".join(lightweight.stream_chat("那要带伞吗")) == "建议带伞。"

    assert {"role": "user", "content": "查一下北京天气"} in captured[0]
    assert {"role": "assistant", "content": "北京今天有雨。"} in captured[0]
