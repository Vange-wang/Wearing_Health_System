from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.llm import ConversationHistory, TOOL_SENTINEL
from app.stream_resources import OwnedSyncStream
from app.voice_web_search import CheckedChat, SearchCall, needs_agent_check


def model_with(*responses):
    model = Mock()
    model.conversation_history = ConversationHistory()
    model._get_messages.return_value = [{"role": "system", "content": ""}]
    model._stream_messages.side_effect = [
        OwnedSyncStream(iter(chunks), SimpleNamespace(close=lambda: None), {}, lambda: None)
        for chunks in responses
    ]
    return model


def test_chat_releases_first_sentence_before_reading_the_second():
    def chunks():
        yield "今天天气这个词"
        yield "有四个字。"
        yield "下一句。"
    model = model_with(chunks())
    stream = CheckedChat(model).stream_chat("聊聊语言")
    assert next(stream) == "今天天气这个词有四个字。"
    assert list(stream) == ["下一句。"]
    assert model._stream_messages.call_count == 1


@pytest.mark.parametrize("decision", [[SearchCall("王者万象棋")], ["我暂时", "无法联网搜索。"]])
def test_search_precedes_reply_and_commits_only_final_answer(monkeypatch, decision):
    lookup = Mock(return_value=[{"url": "https://example.com", "text": "资料"}])
    monkeypatch.setattr("app.voice_web_search.search_pages", lookup)
    extraction = [] if isinstance(decision[0], SearchCall) else [[SearchCall("王者万象棋")]]
    model = model_with(decision, *extraction, ["据官网介绍，", "这是策略游戏。"])
    stream = CheckedChat(model).stream_chat("王者万象棋")
    stream.defer_history_commit()
    assert next(stream) is TOOL_SENTINEL
    lookup.assert_not_called()
    assert "".join(stream) == "据官网介绍，这是策略游戏。"
    assert not model.conversation_history.snapshot()
    stream.commit_history()
    assert model.conversation_history.snapshot()[-1]["content"] == "据官网介绍，这是策略游戏。"
    assert stream.stats["web_search_status"] == "success"
    lookup.assert_called_once_with("王者万象棋")


@pytest.mark.parametrize("text, checked", [
    ("晚上好！", False), ("给我讲个笑话", False), ("你好，帮我查一下消息", True),
    ("今天心情很好，王者万象棋最近怎么样", True), ("王者万象棋", True),
])
def test_only_complete_social_utterances_bypass_check(text, checked):
    assert needs_agent_check(text) is checked


def test_cancel_before_lookup(monkeypatch):
    lookup = Mock()
    monkeypatch.setattr("app.voice_web_search.search_pages", lookup)
    model = model_with([SearchCall("公开主题")])
    stream = CheckedChat(model).stream_chat("问游戏")
    assert next(stream) is TOOL_SENTINEL
    stream.close()
    assert list(stream) == []
    assert not model.conversation_history.snapshot()
    lookup.assert_not_called()


def test_empty_search_does_not_commit_or_fabricate(monkeypatch):
    monkeypatch.setattr("app.voice_web_search.search_pages", lambda _: [])
    model = model_with([SearchCall("公开主题")])
    stream = CheckedChat(model).stream_chat("问游戏")
    assert list(stream) == [TOOL_SENTINEL, "这次搜索没有取得可核实的网页资料。"]
    assert stream.stats["web_search_status"] == "failed"
    assert not model.conversation_history.snapshot()
