"""V2 supplier adapter: tool-free model + exact read-only weather provider only."""
import asyncio
import copy
import time
from types import SimpleNamespace
from .llm import ConversationHistory
from .mimo_llm import DeepSeekVoiceLLM
from .mimo_asr import MiMoBufferedASR
from .turn_asr import TurnASR
from .weather import WeatherRouteCandidate, OpenMeteoWeatherSearch
from .pipeline import StreamingPipeline, TimingRecord
from .router import LIGHTWEIGHT
from .voice_turn import TurnStore, Limits, TurnError
from .stream_resources import OwnedSyncStream

WRITE_INTENTS=('发消息','发邮件','发送','支付','购买','下单','删除','修改文件','写入','创建提醒','设置闹钟','订票','转账','上传','发布')
PENDING_ACTION='这项操作需要在完整发言确认后另行提交，当前没有执行。'

class PendingAction:
    name='pending_action'
    def __init__(self,history):self.conversation_history=history
    def stream_chat(self,text):
        return OwnedSyncStream(iter([PENDING_ACTION]),SimpleNamespace(close=lambda:None),{},
                               lambda:self.conversation_history.remember(text,PENDING_ACTION))

class BoundedAnswer:
    def __init__(self,backend):
        self.backend=backend;self.name=backend.name
    def stream_chat(self,text):
        inner=self.backend.stream_chat(text)
        inner.defer_history_commit()
        class Stream:
            count=0
            stats=inner.stats
            def __iter__(self):return self
            def __next__(self):
                part=next(inner)
                if not isinstance(part,str):raise TurnError('invalid_model_output')
                self.count+=len(part)
                if self.count>8000:raise TurnError('answer_capacity',413)
                return part
            def defer_history_commit(self):inner.defer_history_commit()
            def commit_history(self):inner.commit_history()
            def close(self):inner.close()
        return Stream()


class TurnHistory(ConversationHistory):
    def remember_input(self,text):
        with self._lock:
            self._messages.append({'role':'user','content':text})
            self._last_active=time.time()


class VoiceV2Service:
    def __init__(self, asr, model, tts, *, limits=Limits(), weather=False):
        # Exact classes, not user-controlled names or prompt-only policy.
        # Hermes and subclasses with arbitrary tool methods are rejected.
        if type(model) is not DeepSeekVoiceLLM:
            raise ValueError('v2 only permits tool-free DeepSeek and bounded MiMo ASR')
        self.turn_asr=TurnASR(asr)
        self.asr,self.model,self.tts,self.weather=asr,model,tts,weather
        self.store=TurnStore(TurnHistory(),limits)
        self.initialized=True
        self.recent_requests={}
        self.last_model_report={}
        self._answer_cleanup_tasks=set()

    def health(self):
        from .voice_v2_health import snapshot
        return snapshot(self)

    def outcome(self,stage,status,code=None):
        self.recent_requests[stage]={'status':status,'code':code,'at':time.time()}

    async def recognize(self,pcm):
        # Private stream owns an explicit copy; provider finally.clear cannot
        # mutate the segment owner while another revision still needs its ASR.
        self.outcome('asr','running')
        try:
            text=await self.turn_asr.recognize(pcm)
            self.outcome('asr','success')
            return text
        except asyncio.CancelledError:
            self.outcome('asr','cancelled')
            raise
        except Exception as exc:
            from .asr import ASRError
            rejected=isinstance(exc,ASRError) and str(exc) in ('no_signal','no_meaningful_speech')
            self.outcome('asr','rejected' if rejected else 'failed','no_speech' if rejected else 'recognition_failed')
            raise

    async def answer(self,text,turn,revision):
        if len(self.store.output_leases)>=2:raise TurnError('output_capacity',413)
        lease=object()
        history=ConversationHistory()
        # Candidate-private input/history. Existing pipeline may commit only here.
        with history._lock:
            history._messages.extend(self.store.history.snapshot())
        model=copy.copy(self.model)
        model.conversation_history=history
        model.memory=None
        model.tool_route_configured=False
        model.direct_weather_configured=self.weather
        backend=model
        if self.weather:
            backend=WeatherRouteCandidate(model,model,OpenMeteoWeatherSearch(),enabled=True,general_locations=True)
        weather_request=self.weather and backend.handles_current_weather(text)
        if any(word in text for word in WRITE_INTENTS):backend=PendingAction(history)
        router=None
        if not weather_request and not isinstance(backend,PendingAction):
            # V2 keeps its text/followup semantics; only select the existing fast path.
            router=SimpleNamespace(normalize_asr=lambda value:value,
                                   classify_followup=lambda value:None,
                                   route=lambda *_:LIGHTWEIGHT)
        backend=BoundedAnswer(backend)
        pipe=StreamingPipeline(None,backend,self.tts,None,sentence_gap_ms=0,
                               max_frame_bytes=256*1024,tts_workers=2,queue_capacity=4,router=router)
        self.outcome('answer','running')
        timing=TimingRecord();timing.captions_enabled=True;timing.private_input=True
        gen=pipe.run_text(text,timing)
        quiescent=asyncio.Event()
        self.store.output_leases[lease]=quiescent
        try:
            async for data in gen:
                if not self.store.current(turn,revision):raise TurnError('stale_revision')
                yield data
            if timing.get('weather_status')=='failed':raise TurnError('weather_failed')
            messages=history.snapshot()
            if len(messages)<2 or messages[-2].get('content')!=text or messages[-1].get('role')!='assistant':
                raise TurnError('candidate_history_missing')
            if self.store.current(turn,revision):turn.draft=(text,messages[-1]['content'])
            self.outcome('answer','generated')
        except asyncio.CancelledError:
            self.outcome('answer','cancelled')
            raise
        except Exception:
            self.outcome('answer','failed','answer_failed')
            raise
        finally:
            self.last_model_report={'last_call_ok':getattr(model,'last_call_ok',None),
                                    'response_model':getattr(model,'last_response_model',None)}
            def released():
                self.store.output_leases.pop(lease,None)
                quiescent.set()
            async def cleanup():
                try:
                    await gen.aclose()
                finally:
                    try:
                        await timing.resources.aclose()
                    finally:
                        # Even a cleanup error must register the callback; the
                        # resource owner, not response cancellation, gates release.
                        timing.resources.when_quiescent(released)
            cleanup_task=asyncio.create_task(cleanup())
            self._answer_cleanup_tasks.add(cleanup_task)
            def finished(task):
                self._answer_cleanup_tasks.discard(task)
                if not task.cancelled():
                    task.exception()  # Observe detached cleanup failures.
            cleanup_task.add_done_callback(finished)
            # Repeated response cancellation cannot abandon cleanup or its lease.
            await asyncio.shield(cleanup_task)

    async def close(self):
        self.initialized=False
        await self.store.close()
        pending=list(self.store.output_leases.values())
        if pending:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in pending)),5)
