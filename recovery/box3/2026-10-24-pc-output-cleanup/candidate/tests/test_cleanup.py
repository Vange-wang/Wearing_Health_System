import asyncio,importlib.util,sys,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
workspace=root.parents[3]
sys.path.insert(0,str(workspace/'voice-bridge'))
from app.llm import ConversationHistory
from app.voice_turn import TurnStore,TurnError

def load(path,name):
 spec=importlib.util.spec_from_file_location('app.'+name,path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
class Resource:
 quiescent=False
 def __init__(self):self.entered=asyncio.Event();self.release=asyncio.Event()
 async def close(self):self.entered.set();await self.release.wait();self.quiescent=True
class Pipe:
 mode='blocked';opened=[]
 def __init__(self,asr,model,*a,**kw):self.model=model
 async def run_text(self,text,timing):
  if self.mode=='blocked':
   resource=Resource();Pipe.opened.append((resource,timing.resources))
   async def opened():return resource
   timing.resources.task(opened(),resource_result=True)
   await asyncio.sleep(0);await asyncio.sleep(0)
  yield b'public-fixture'
  if self.mode=='blocked':await asyncio.Event().wait()
  elif self.mode=='error':raise RuntimeError('fixture_failure')
  else:self.model.backend.conversation_history.remember(text,'fixture reply')
def service(module):
 svc=module.VoiceV2Service.__new__(module.VoiceV2Service)
 svc.model=SimpleNamespace(name='fixture');svc.tts=None;svc.weather=False
 svc.store=TurnStore(ConversationHistory());svc.store.current=lambda *_:True
 svc.recent_requests={};svc.last_model_report={};svc._answer_cleanup_tasks=set()
 return svc
async def one(module,double):
 svc=service(module);Pipe.mode='blocked';pending=[]
 with patch.object(module,'StreamingPipeline',Pipe):
  for index in range(2):
   seen=asyncio.Event()
   async def consume():
    async for _ in svc.answer('public fixture',SimpleNamespace(draft=None),1):seen.set()
   task=asyncio.create_task(consume());await asyncio.wait_for(seen.wait(),1)
   resource,resources=Pipe.opened[-1]
   assert not svc._answer_cleanup_tasks or index>0 # no cleanup task on first-frame path
   task.cancel();await asyncio.wait_for(resource.entered.wait(),1)
   if double:
    task.cancel()
    try:await task
    except asyncio.CancelledError:pass
   pending.append((task,resource,resources))
  assert len(svc.store.output_leases)==2
  try:await anext(svc.answer('public fixture',SimpleNamespace(draft=None),1))
  except TurnError as exc:assert exc.code=='output_capacity'
  else:raise AssertionError('live resources incorrectly released')
  for task,resource,resources in pending:resource.release.set()
  for task,resource,resources in pending:
   try:await task
   except asyncio.CancelledError:pass
   await asyncio.wait_for(resources._cleanup_task,1)
  if svc._answer_cleanup_tasks:await asyncio.gather(*svc._answer_cleanup_tasks,return_exceptions=True)
  await asyncio.sleep(0)
  leases=len(svc.store.output_leases);assert all(r.quiescent and res.pending_sync==0 for _,r,res in pending)
  Pipe.mode='normal';code=None;frames=[]
  try:frames=[x async for x in svc.answer('public fixture',SimpleNamespace(draft=None),1)]
  except TurnError as exc:code=exc.code
  return {'double_cancel':double,'quiescent_after_release':True,'leases_after_cleanup':leases,'next_code':code,'next_frames':len(frames)}
async def normal(module):
 svc=service(module)
 with patch.object(module,'StreamingPipeline',Pipe):
  Pipe.mode='normal';frames=[x async for x in svc.answer('public fixture',SimpleNamespace(draft=None),1)]
  assert frames and not svc.store.output_leases
  Pipe.mode='error'
  try:[x async for x in svc.answer('public fixture',SimpleNamespace(draft=None),1)]
  except RuntimeError:pass
  else:raise AssertionError('error swallowed')
  assert not svc.store.output_leases
 return {'normal_and_exception_cleanup':'PASS'}
async def main():
 before=load(root/'before/voice_v2_service.py','cleanup_baseline')
 candidate=load(root/'pc/app/voice_v2_service.py','cleanup_candidate')
 red=await one(before,True)
 assert red['leases_after_cleanup']==2 and red['next_code']=='output_capacity'
 green=await one(candidate,True)
 assert green['leases_after_cleanup']==0 and green['next_frames']==1 and green['next_code'] is None
 single=await one(candidate,False);assert single['leases_after_cleanup']==0 and single['next_frames']==1
 result={'baseline_red':red,'candidate_double_cancel':green,'candidate_single_cancel':single,'candidate_normal':await normal(candidate)}
 (root/'evidence/cleanup-tests.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps(result))
if __name__=='__main__':asyncio.run(main())
