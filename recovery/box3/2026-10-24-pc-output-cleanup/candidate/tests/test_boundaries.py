import asyncio,threading,json,logging
from types import SimpleNamespace
from unittest.mock import patch
from test_cleanup import load,root,service
logging.getLogger('voice-bridge.resources').disabled=True
class Stream:
 def __init__(self):self.closed=False
 def close(self):self.closed=True
class AsyncFailure:
 quiescent=False
 def __init__(self):self.callbacks=[];self.calls=0
 async def close(self):self.calls+=1;raise RuntimeError('public-close-fixture')
 def when_quiescent(self,cb):self.callbacks.append(cb)
 def actual_exit(self):
  self.quiescent=True
  for cb in self.callbacks:cb()
class BoundaryPipe:
 mode='sync';last=None
 def __init__(self,*a,**kw):pass
 def run_text(self,text,timing):
  if self.mode=='gen_close_error':
   class BrokenClose:
    def __aiter__(self):return self
    async def __anext__(self):
     if not getattr(self,'sent',False):self.sent=True;return b'fixture'
     await asyncio.Event().wait()
    async def aclose(self):raise RuntimeError('public-generator-close-fixture')
   BoundaryPipe.last={'resources':timing.resources};return BrokenClose()
  return self.stream(timing)
 async def stream(self,timing):
  resources=timing.resources;state={'resources':resources};BoundaryPipe.last=state
  if self.mode in ('sync','late'):
   state['gate']=threading.Event();state['entered']=threading.Event();state['stream']=Stream()
   def work():state['entered'].set();state['gate'].wait(3);return state['stream'] if self.mode=='late' else 1
   resources.task(resources.call(work,returns_stream=self.mode=='late'))
   while not state['entered'].is_set():await asyncio.sleep(0)
  elif self.mode=='queue':
   queue=asyncio.Queue(1);queue.put_nowait(1);state['worker']=resources.task(queue.put(2));await asyncio.sleep(0)
  elif self.mode=='close_failure':
   state['resource']=AsyncFailure()
   async def opened():return state['resource']
   resources.task(opened(),resource_result=True);await asyncio.sleep(0);await asyncio.sleep(0)
  elif self.mode=='preframe':
   state['started']=True;resources.task(asyncio.Event().wait());await asyncio.Event().wait()
  yield b'fixture';await asyncio.Event().wait()
async def settle(svc):
 if svc._answer_cleanup_tasks:await asyncio.gather(*svc._answer_cleanup_tasks,return_exceptions=True)
 await asyncio.sleep(0)
async def case(module,mode):
 svc=service(module);BoundaryPipe.mode=mode;BoundaryPipe.last=None;seen=asyncio.Event()
 with patch.object(module,'StreamingPipeline',BoundaryPipe):
  async def consume():
   async for _ in svc.answer('public fixture',SimpleNamespace(draft=None),1):seen.set()
  task=asyncio.create_task(consume())
  if mode=='preframe':
   while BoundaryPipe.last is None or not BoundaryPipe.last.get('started'):await asyncio.sleep(0)
   assert not seen.is_set()
  else:await asyncio.wait_for(seen.wait(),1)
  task.cancel()
  try:await task
  except (asyncio.CancelledError,RuntimeError):pass
  await settle(svc);state=BoundaryPipe.last
  if mode in ('sync','late'):
   assert len(svc.store.output_leases)==1 and state['resources'].pending_sync==1
   state['gate'].set()
   for _ in range(1000):
    if not svc.store.output_leases:break
    await asyncio.sleep(.001)
   assert not svc.store.output_leases and state['resources'].pending_sync==0
   if mode=='late':assert state['stream'].closed
  elif mode=='close_failure':
   assert state['resource'].calls==2 and len(svc.store.output_leases)==1
   state['resource'].actual_exit();await asyncio.sleep(0);assert not svc.store.output_leases
  else:
   assert not svc.store.output_leases
   if mode=='queue':assert state['worker'].done()
  return {'mode':mode,'pass':True}
async def main():
 module=load(root/'pc/app/voice_v2_service.py','boundary_candidate')
 result=[await asyncio.wait_for(case(module,m),5) for m in ['sync','late','preframe','queue','gen_close_error','close_failure']]
 (root/'evidence/boundary-tests.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
asyncio.run(main())
