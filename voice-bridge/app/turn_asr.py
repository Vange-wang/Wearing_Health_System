"""Per-turn ASR adapter; private RAM input and real worker lifetime ownership."""
import asyncio
import numpy as np
from .asr import SherpaOnnxASR, ASRError
from .mimo_asr import MiMoBufferedASR
from .input_qualification import pcm_has_signal, meaningful_text

class TurnASR:
    def __init__(self,provider):
        if type(provider) not in (SherpaOnnxASR,MiMoBufferedASR):
            raise ValueError('unsupported bounded turn ASR provider')
        self.provider=provider

    async def recognize(self,pcm):
        if len(pcm)>480000 or not pcm_has_signal(pcm):raise ASRError('no_signal')
        if type(self.provider) is MiMoBufferedASR:
            stream=self.provider.create_stream()
            stream.pcm.extend(pcm)
            result=await self.provider.final_async(stream)
        else:
            # Copy before starting the worker. Segment cleanup must never race
            # a native decoder still accessing its samples.
            samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.0
            def decode():
                try:
                    r=self.provider.recognizer;s=r.create_stream()
                    s.accept_waveform(16000,samples);r.decode_stream(s)
                    return s.result.text.strip()
                finally:samples.fill(0)
            task=asyncio.create_task(asyncio.to_thread(decode))
            cancelled=False
            while True:
                try:
                    result=await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    cancelled=True
                    # The caller remains charged to the store's bounded ASR
                    # cleanup set until the real native worker has exited.
                    if task.done():break
            if cancelled:
                if task.done() and not task.cancelled():task.exception()
                raise asyncio.CancelledError
        if not meaningful_text(result):raise ASRError('no_meaningful_speech')
        return result.strip()

def select_turn_asr(config,existing):
    engine=config.voice_v2_asr_engine
    if engine=='configured':return existing
    if engine=='sensevoice':
        return existing if type(existing) is SherpaOnnxASR else SherpaOnnxASR(config.asr_model_dir,16000)
    return existing if type(existing) is MiMoBufferedASR else MiMoBufferedASR(480000,config.asr_mimo_timeout)
