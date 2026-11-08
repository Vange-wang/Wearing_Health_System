"""Public/fake regressions: paired cached captions and real answer timing."""
import asyncio
import struct
import time
from types import SimpleNamespace as NS

import pytest

from app.caption_protocol import CAPTION_MARKER
from app.pipeline import StreamingPipeline, TimingRecord, decode_frame
from app.router import Router
from app.tts import wrap_pcm_as_wav


class LLM:
    name = "fixture"
    stats = {}
    def stream_chat(self, text): return iter(["正式回答。"])


class TTS:
    async def stream_synthesize(self, text):
        yield wrap_pcm_as_wav(bytes(320), 16000)


def test_cached_ack_caption_is_paired_and_answer_stays_unknown_until_ready():
    async def exercise():
        ready = asyncio.Event()
        class HeldTTS:
            async def stream_synthesize(self, text):
                await ready.wait()
                yield wrap_pcm_as_wav(bytes(320), 16000)
        pipe = StreamingPipeline(None, LLM(), HeldTTS(), None, tts_workers=1,
                                 sentence_gap_ms=0, acknowledgements={"query": [("正在查询。", b"ACK")]})
        timing = TimingRecord()
        timing.captions_enabled = True
        timing.audio_start_perf = time.perf_counter() - .2
        timing["audio_origin"] = "pcm_complete"
        stream = pipe.run_text("公开问题", timing)
        try:
            first = await asyncio.wait_for(anext(stream), 2)
            assert decode_frame(first)[0] == b"ACK"
            assert timing["comfort_first_ms"] >= 200
            assert timing["answer_first_ms"] is None
            caption = await anext(stream)
            assert caption.startswith(CAPTION_MARKER)
            length = struct.unpack(">Q", caption[4:12])[0]
            assert caption[12:12+length].decode() == "正在查询。"
            ready.set()
            rest = [frame async for frame in stream]
            assert decode_frame(rest[0])[0].startswith(b"RIFF")
            assert timing["answer_first_ms"] >= timing["comfort_first_ms"]
            assert timing["audio_origin"] == "pcm_complete"
        finally:
            ready.set()
            await stream.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize("ack", [None, b"OLD_ACK"])
def test_no_invented_caption_for_legacy_audio_and_no_false_comfort_timing(ack):
    async def exercise():
        pipe = StreamingPipeline(None, LLM(), TTS(), None, tts_workers=1, sentence_gap_ms=0,
                                 acknowledgements={"query": [ack]} if ack else {})
        timing = TimingRecord(); timing.captions_enabled=True
        frames = [frame async for frame in pipe.run_text("公开问题",timing)]
        captions = [f[12:].decode() for f in frames if f.startswith(CAPTION_MARKER)]
        assert captions == ["正式回答。"]
        assert timing["answer_first_ms"] is not None
        assert (timing["comfort_first_ms"] is None) == (ack is None)
        assert timing["audio_origin"] == "text_ready"
    asyncio.run(exercise())


def test_restored_tools_keep_pinned_deepseek_and_shared_history(monkeypatch):
    from app import llm, mimo_llm
    history=llm.ConversationHistory()
    made=[]
    monkeypatch.setattr(llm,"HermesLLM",lambda *a,**k: made.append(("hermes",a,k)) or "hermes")
    monkeypatch.setattr(mimo_llm,"DeepSeekVoiceLLM",lambda *a,**k: made.append(("deepseek",a,k)) or "deepseek")
    cfg=NS(llm_engine="hermes",lw_engine="deepseek",llm_api_key=lambda:"fixture-hermes",
           llm_api_server_url="http://127.0.0.1:8780/v1",llm_model="hermes-agent",
           lightweight_api_key=lambda:"fixture-deepseek",lw_base_url="https://api.deepseek.com",
           lw_model="deepseek-chat",user_profile_path="unused")
    assert llm.create_llm(cfg,history)=="hermes"
    assert llm.create_lightweight_llm(cfg,conversation_history=history)=="deepseek"
    assert all(item[2]["conversation_history"] is history for item in made)
    router=Router(tool_keywords=["天气","搜索"],skill_keywords=[])
    assert router.route("新加坡天气怎么样",False)=="hermes"
    assert router.route("你好",False)=="lightweight"


@pytest.mark.parametrize("with_comfort", [False, True])
def test_http_header_and_completion_log_distinguish_answer(monkeypatch, caplog, with_comfort):
    import json
    import logging
    from fastapi.testclient import TestClient
    from app import main
    from app.device_auth import install_device_auth
    class ASR:
        def create_stream(self): return object()
        def accept(self,*a): pass
        def partial(self,*a): return ""
        def final(self,*a): return "公开问题"
    pipe=StreamingPipeline(None,LLM(),TTS(),None,tts_workers=1,sentence_gap_ms=0,
        acknowledgements={"query":[("正在查询。",wrap_pcm_as_wav(bytes(320),16000))]} if with_comfort else {})
    monkeypatch.setattr(main,"streaming_asr",ASR())
    monkeypatch.setattr(main,"pipeline",pipe)
    monkeypatch.setattr(main.app.state,"device_auth",main.app.state.device_auth)
    install_device_auth(main.app,token="fixture-only",mode="required")
    caplog.set_level(logging.INFO,logger="voice-bridge")
    response=TestClient(main.app).post('/api/v1/voice/stream',content=bytes(320),
        headers={"X-Device-Token":"fixture-only","X-Voice-Captions":"after-audio-v1"})
    assert response.status_code==200
    header=json.loads(response.headers['x-timing'])
    assert header['audio_origin']=='pcm_complete' and header['answer_open_ms_is_legacy'] is True
    assert (header['answer_first_ms'] is None)==with_comfort
    assert (header['comfort_first_ms'] is not None)==with_comfort
    completed=[json.loads(r.message) for r in caplog.records if r.message.startswith('{')
               and '"event": "request_done"' in r.message][-1]
    assert completed['answer_first_ms'] is not None
    if with_comfort:
        assert completed['answer_first_ms']>=completed['comfort_first_ms']
