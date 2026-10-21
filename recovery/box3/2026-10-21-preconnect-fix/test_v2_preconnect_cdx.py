"""Actual V2 answer/pipeline, gated supplier I/O only; no network or config."""
import asyncio,importlib.util,sys,threading
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'voice-bridge').is_dir())
sys.path.insert(0,str(ROOT/'voice-bridge'))
sys.path.insert(0,str(ROOT/'Code文档/测试报告/2026-10-17-v2整包联合验证-R1/evidence/service-tests'))
from test_v2 import supplier_service,put,SESSION
from app.tts import wrap_pcm_as_wav
spec=importlib.util.spec_from_file_location('app.v2_preconnect_candidate',HERE/'source/app/voice_v2_service.py')
candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)

class TTS:
    def __init__(self):
        self.opened=asyncio.Event();self.opens=0;self.pre_used=0;self.normal_used=0;self.closed=0
    async def open_preconnect(self):
        self.opens+=1;self.opened.set();parent=self
        class Connection:
            async def stream_synthesize(self,text):
                parent.pre_used+=1;yield wrap_pcm_as_wav(bytes(320),16000)
            async def close(self):parent.closed+=1
        return Connection()
    async def stream_synthesize(self,text):
        self.normal_used+=1;yield wrap_pcm_as_wav(bytes(320),16000)

async def service(tts,weather=False):
    baseline,calls=supplier_service()
    svc=candidate.VoiceV2Service(baseline.asr,baseline.model,tts,weather=weather)
    svc.store.reset_session(SESSION,svc.store.session_challenge())
    turn,segment=put(svc.store,0,'公开测试问题');await segment.task
    return svc,turn,calls

def gate_model(svc):
    release=threading.Event();entered=asyncio.Event();loop=asyncio.get_running_loop()
    original=svc.model.client.chat.completions.create
    def create(**kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(2),'test supplier not released'
        return original(**kwargs)
    svc.model.client.chat.completions.create=create
    return entered,release

async def collect(svc,turn,text,frames):
    async for frame in svc.answer(text,turn,1):frames.append(frame)

@pytest.mark.parametrize('weather',[False,True],ids=['ordinary','weather_enabled_ordinary'])
def test_answer_preconnect_starts_before_model_returns_and_audio_is_delivered(weather):
    async def go():
        tts=TTS();svc,turn,calls=await service(tts,weather);entered,release=gate_model(svc)
        frames=[];text='一加一等于几？';task=asyncio.create_task(collect(svc,turn,text,frames))
        try:
            await asyncio.wait_for(entered.wait(),1)
            await asyncio.wait_for(tts.opened.wait(),0.25)
            assert not release.is_set() and not frames and not calls
            release.set();await asyncio.wait_for(task,2)
            assert any(b'RIFF' in frame for frame in frames)
            assert tts.opens==1 and tts.pre_used==1 and tts.normal_used==0
            assert calls==[text] and turn.draft[0]==text
            assert svc.recent_requests['answer']['status']=='generated' and not svc.store.history.snapshot()
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True);await svc.close()
        assert tts.closed>=1 and not svc.store.output_leases
    asyncio.run(go())

def test_continuation_cancels_actual_answer_and_closes_early_preconnect():
    async def go():
        tts=TTS();svc,turn,calls=await service(tts);entered,release=gate_model(svc)
        frames=[];task=asyncio.create_task(collect(svc,turn,'一加一等于几？',frames));turn.candidate=task
        try:
            await asyncio.wait_for(entered.wait(),1);await asyncio.wait_for(tts.opened.wait(),1)
            svc.store.event(SESSION,1,2,1,'continuation')
            await asyncio.sleep(0);release.set()
            result=await asyncio.gather(task,return_exceptions=True)
            assert isinstance(result[0],asyncio.CancelledError) and not frames
            assert turn.revision==2 and turn.segments[0].text=='公开测试问题'
            assert svc.recent_requests['answer']['status']=='cancelled' and not svc.store.history.snapshot()
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True);await svc.close()
        assert tts.opens==1 and tts.closed>=1 and not svc.store.output_leases
    asyncio.run(go())

def test_actual_weather_search_keeps_normal_TTS_without_idle_preconnect(monkeypatch):
    async def go():
        release=threading.Event();entered=asyncio.Event();loop=asyncio.get_running_loop();search_calls=[]
        class Search:
            def search(self,city,now):
                search_calls.append(city);loop.call_soon_threadsafe(entered.set)
                assert release.wait(2),'test weather supplier not released'
                return dict(city=city,time='2026-10-21T12:00',temp_c=20,condition='晴')
        monkeypatch.setattr(candidate,'OpenMeteoWeatherSearch',Search)
        tts=TTS();svc,turn,model_calls=await service(tts,True)
        frames=[];task=asyncio.create_task(collect(svc,turn,'北京今天天气怎么样？',frames))
        try:
            await asyncio.wait_for(entered.wait(),1);await asyncio.sleep(0)
            assert tts.opens==0 and not frames
            release.set();await asyncio.wait_for(task,2)
            assert search_calls==['北京'] and model_calls==[]
            assert tts.opens==0 and tts.normal_used>=1 and any(b'RIFF' in f for f in frames)
            assert '来源Open-Meteo' in turn.draft[1] and svc.recent_requests['answer']['status']=='generated'
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True);await svc.close()
    asyncio.run(go())
