"""V2 initialization/readiness and request outcomes are independent signals."""
from .asr import SherpaOnnxASR

def snapshot(service):
    if service is None:
        return {'protocol':'voice-v2','process_alive':True,'ready':False,'status':'unavailable',
                'reason':'not_initialized','providers':{},'recent_requests':{}}
    tts=service.tts.health() if service.tts is not None else {}
    asr_ok=service.asr is not None and (
        type(service.asr) is not SherpaOnnxASR or getattr(service.asr,'recognizer',None) is not None)
    model_ok=service.model is not None
    tts_ok=bool(service.tts is not None and tts.get('active_engine') not in (None,'unavailable')
                and tts.get('last_probe_ok') is True)
    ready=bool(service.initialized and asr_ok and model_ok and tts_ok)
    providers={
        'asr':{'provider':getattr(service.asr,'name',type(service.asr).__name__),
               'model':getattr(service.asr,'model','sensevoice' if type(service.asr) is SherpaOnnxASR else None),
               'initialized':asr_ok,'last_call_ok':getattr(service.asr,'last_call_ok',None)},
        'llm':{'provider':getattr(service.model,'name',None),'model':getattr(service.model,'model',None),
               'initialized':model_ok,**service.last_model_report},
        'tts':dict(tts,initialized=service.tts is not None),
    }
    # Recent failure remains visible; it is not evidence of process/network loss.
    return {'protocol':'voice-v2','process_alive':True,'ready':ready,
            'status':'ok' if ready else 'unavailable',
            'reason':None if ready else 'provider_not_ready',
            'providers':providers,'recent_requests':{k:dict(v) for k,v in service.recent_requests.items()}}
