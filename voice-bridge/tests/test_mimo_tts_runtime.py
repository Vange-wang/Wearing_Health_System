"""Actual MiMo provider/engine/pipeline contracts, fake network and credentials."""
import array
import asyncio
import audioop
import base64
import io
import json
from types import SimpleNamespace
import wave

import aiohttp
import pytest
from app import mimo_tts
from app.pipeline import StreamingPipeline, TimingRecord, decode_frame
from app.tts import TTSError, TTSEngine, create_tts
from app.vad import VADGate


def fake_http(monkeypatch, *, partial_error=False, blocked=False, block_first=False, status=200):
    raw = array.array("h", [1000,-1000,500,0]*2400).tobytes()
    observed = {"sessions":[],"responses":[],"requests":[],"raw":raw}
    class Response:
        def __init__(self): self.status=status; self.headers={"content-type":"text/event-stream"}; self.content=self; self.closed=False
        async def __aenter__(self): observed["responses"].append(self); return self
        async def __aexit__(self,*args): self.closed=True
        async def iter_any(self):
            if blocked or getattr(self,"block_this",False): await asyncio.Future()
            for index, data in enumerate((raw[:301],raw[301:10000],raw[10000:])):
                item={"choices":[{"delta":{"audio":{"data":base64.b64encode(data).decode()}}}]}
                yield b"data: "+json.dumps(item).encode()+b"\n\n"
                if partial_error and index==1: raise RuntimeError("SYNTHETIC_SECRET_CANARY")
            yield b"data: [DONE]\n\n"
    class Session:
        def __init__(self,**kwargs):
            assert kwargs["trust_env"] is False and kwargs["connector"]._family==2
            self.connector=kwargs["connector"]; self.closed=False; observed["sessions"].append(self)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): await self.connector.close(); self.closed=True
        def post(self,url,**kwargs):
            assert url==mimo_tts.BASE_URL+"/chat/completions" and kwargs["allow_redirects"] is False
            assert kwargs["headers"]=={"api-key":"SYNTHETIC_NEW_KEY"}
            assert kwargs["json"]["audio"]=={"format":"pcm16","voice":"茉莉"}
            assert kwargs["json"]["stream"] is True and kwargs["json"]["messages"][0]["role"]=="assistant"
            observed["requests"].append(True); response=Response()
            response.block_this=block_first and len(observed["requests"])==1
            return response
    monkeypatch.setattr(mimo_tts,"read_mimo_settings",lambda:"SYNTHETIC_NEW_KEY")
    monkeypatch.setattr(aiohttp,"ClientSession",Session)
    return observed


def test_stateful_stream_odd_chunks_equals_whole_and_closes(monkeypatch):
    observed=fake_http(monkeypatch)
    async def exercise():
        segments=[part async for part in mimo_tts.MiMoTTS().stream_synthesize("公开测试")]
        pcm=bytearray()
        for segment in segments:
            with wave.open(io.BytesIO(segment),"rb") as wav:
                assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(16000,1,2)
                pcm.extend(wav.readframes(wav.getnframes()))
        expected,_=audioop.ratecv(observed["raw"],2,1,24000,16000,None)
        assert bytes(pcm)==expected and len(segments)>=2
        assert len(observed["requests"])==1
        assert all(x.closed for x in observed["sessions"]+observed["responses"])
    asyncio.run(exercise())


def test_full_synthesis_and_health_truthful_factory_and_edge_rollback(monkeypatch):
    fake_http(monkeypatch)
    cfg=SimpleNamespace(tts_primary="mimo",tts_mimo_voice="茉莉",tts_mimo_timeout=15,tts_probe_timeout=15)
    engine=create_tts(cfg)
    assert engine.health()["configured_primary"]==engine.health()["active_engine"]=="mimo"
    async def exercise():
        assert await engine.probe() and engine.last_probe_ok
    asyncio.run(exercise())
    cfg=SimpleNamespace(tts_primary="edge",tts_edge_voice="zh-CN-XiaoxiaoNeural",tts_edge_rate="+5%",tts_edge_pitch="+3Hz")
    assert create_tts(cfg).health()["active_engine"]=="edge"


def test_cancel_closes_exact_request_and_no_retries(monkeypatch):
    observed=fake_http(monkeypatch,blocked=True)
    async def exercise():
        stream=mimo_tts.MiMoTTS().stream_synthesize("公开测试")
        task=asyncio.create_task(stream.__anext__()); await asyncio.sleep(0); task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        await stream.aclose()
        assert len(observed["requests"])==1 and all(x.closed for x in observed["sessions"]+observed["responses"])
    asyncio.run(exercise())


@pytest.mark.parametrize("status",[401,429,500])
def test_http_failure_is_safe_and_closed_without_fallback(monkeypatch,status):
    observed=fake_http(monkeypatch,status=status)
    async def exercise():
        with pytest.raises(TTSError) as exc:
            async for _ in mimo_tts.MiMoTTS().stream_synthesize("公开测试"): pass
        assert str(status) in str(exc.value) and "SYNTHETIC_NEW_KEY" not in str(exc.value)
        assert len(observed["requests"])==1 and all(x.closed for x in observed["sessions"]+observed["responses"])
    asyncio.run(exercise())


def test_partial_failure_no_replay_and_safe_error(monkeypatch):
    observed=fake_http(monkeypatch,partial_error=True)
    async def exercise():
        segments=[]
        with pytest.raises(TTSError) as exc:
            async for part in mimo_tts.MiMoTTS().stream_synthesize("公开测试"): segments.append(part)
        assert segments and "CANARY" not in str(exc.value) and exc.value.__suppress_context__
        assert len(observed["requests"])==1 and all(x.closed for x in observed["sessions"]+observed["responses"])
    asyncio.run(exercise())


def test_existing_pipeline_frames_and_resources_unchanged(monkeypatch):
    observed=fake_http(monkeypatch)
    class Router:
        def normalize_asr(self,text): return text
        def classify_followup(self,text): return "replay"
    async def exercise():
        engine=TTSEngine(mimo_tts.MiMoTTS())
        pipeline=StreamingPipeline(None,None,engine,VADGate(enabled=False),router=Router())
        pipeline._commit_last_round("公开问题","公开测试","lightweight")
        timing=TimingRecord()
        frames=[f async for f in pipeline.run_text("公开问题",timing=timing)]
        assert frames
        for frame in frames:
            wav,remaining=decode_frame(frame); assert not remaining and wav[:4]==b"RIFF"
        await asyncio.sleep(0)
        assert timing.resources.pending_sync==0 and all(t.done() for t in timing.resources._tasks)
        assert all(x.closed for x in observed["sessions"]+observed["responses"])
    asyncio.run(exercise())


def test_newfile_reader_stops_before_volc_and_no_environment(monkeypatch):
    prefix=b"".join((name+'='+json.dumps(value)+'\n').encode() for name,value in zip(mimo_tts.FIELDS,["SYNTHETIC_NEW_KEY",mimo_tts.BASE_URL,mimo_tts.MODEL]))
    class Source(io.BytesIO):
        def read(self,size=-1):
            assert self.tell()<len(prefix),"must not read Volc value"
            return super().read(size)
    class File:
        def open(self,*args,**kwargs): return Source(prefix+b'FORBIDDEN_VOLC="secret"\n')
    assert mimo_tts.read_mimo_settings(File())=="SYNTHETIC_NEW_KEY"


def test_concurrent_cancel_does_not_close_other_request_or_mix_pcm(monkeypatch):
    observed=fake_http(monkeypatch,block_first=True)
    async def exercise():
        provider=mimo_tts.MiMoTTS()
        first=provider.stream_synthesize("公开请求一")
        blocked=asyncio.create_task(first.__anext__());await asyncio.sleep(0)
        second=[part async for part in provider.stream_synthesize("公开请求二")]
        blocked.cancel()
        with pytest.raises(asyncio.CancelledError):await blocked
        await first.aclose()
        pcm=bytearray()
        for segment in second:
            with wave.open(io.BytesIO(segment),"rb") as wav:pcm.extend(wav.readframes(wav.getnframes()))
        expected,_=audioop.ratecv(observed["raw"],2,1,24000,16000,None)
        assert bytes(pcm)==expected and len(observed["requests"])==2
        assert all(x.closed for x in observed["sessions"]+observed["responses"])
    asyncio.run(exercise())
