import asyncio

import pytest

from app.asr import SherpaOnnxASR
from app.llm import ConversationHistory
from app.mimo_llm import DeepSeekVoiceLLM
from app.pipeline import SEARCH_FINISHED, SEARCH_STARTED
from app.stream_resources import OwnedSyncStream
from app.tts import wrap_pcm_as_wav
from app.voice_turn import Turn
from app.voice_v2_service import VoiceV2Service
from app.voice_web_search import SearchCall


class Speech:
    async def synthesize(self, text):
        return wrap_pcm_as_wav(bytes(320), 16000)


class Response:
    def close(self):
        pass


@pytest.mark.parametrize("text,capable,expected", [
    ("广州今天的天气怎么样", True, True),
    ("广州今天的天气怎么样", False, False),
    ("今天天气怎么样", True, False),
    ("王者万象棋", True, True),
    ("你好", True, False),
])
def test_search_indicator_tracks_real_lookup(monkeypatch, text, capable, expected):
    model = object.__new__(DeepSeekVoiceLLM)
    model.conversation_history = ConversationHistory()
    service = VoiceV2Service(object.__new__(SherpaOnnxASR), model, Speech(), weather=True, web_search=True)
    turn = Turn("test-session", 1)
    service.store.turn = turn
    turn.search_ui_revision = turn.revision if capable else 0
    lookups = []

    def weather(city, now):
        lookups.append(city)
        return dict(city=city, time="2026-11-10T09:30", temp_c=23, condition="晴")

    def ordinary(self, prompt):
        return OwnedSyncStream(iter(["你好。"]), Response(), {},
            lambda: self.conversation_history.remember(prompt, "你好。"))

    def lookup(query):
        lookups.append(query)
        return "公开资料"

    responses = iter(([SearchCall("王者万象棋")], ["这是一款游戏。"]))
    monkeypatch.setattr(DeepSeekVoiceLLM, "stream_chat", ordinary)
    monkeypatch.setattr(DeepSeekVoiceLLM, "_get_messages", lambda *a: [{"role":"system","content":""}])
    monkeypatch.setattr(DeepSeekVoiceLLM, "_stream_messages", lambda *a, **kw:
        OwnedSyncStream(iter(next(responses)), Response(), {}, lambda: None))
    monkeypatch.setattr("app.voice_web_search.search_pages", lookup)
    monkeypatch.setattr(service.weather_search, "search", weather)
    async def collect():
        return [f async for f in service.answer(text, turn, turn.revision)]

    frames = asyncio.run(collect())
    assert frames.count(SEARCH_STARTED) == frames.count(SEARCH_FINISHED) == int(expected)
    if expected:
        assert frames[0] is SEARCH_STARTED
        assert isinstance(frames[frames.index(SEARCH_FINISHED)-1], bytes)
        assert len(lookups) == 1
    assert any(isinstance(f, bytes) for f in frames)

def test_cancel_between_search_marker_and_weather_lookup(monkeypatch):
    model = object.__new__(DeepSeekVoiceLLM)
    model.conversation_history = ConversationHistory()
    service = VoiceV2Service(object.__new__(SherpaOnnxASR), model, Speech(), weather=True)
    turn = Turn("test-session", 1, search_ui_revision=1)
    service.store.turn = turn
    monkeypatch.setattr(service.weather_search, "search",
                        lambda *args: pytest.fail("cancelled search executed"))

    async def cancel():
        stream = service.answer("广州今天的天气怎么样", turn, 1)
        assert await anext(stream) is SEARCH_STARTED
        await stream.aclose()
        assert not service.store.output_leases

    asyncio.run(cancel())
