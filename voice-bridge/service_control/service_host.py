"""Managed child graceful-stop seam; shared reused services never use it."""
import os
import runpy
import threading
import time
import json
import re
from .ipc import PipeServer
from .provider import service_paths,service_arguments
from .windows import process_created,Security,Mutex
from .intent import IntentStore
from .role_lease import lease_paths


def admitted_launch(paths,role,owner,attempt_id,identity,*,fixture=False,intent_generation=None):
    """Durable admission binds this child to one previously saved attempt."""
    try:
        if not re.fullmatch(r'[0-9a-f]{32}',attempt_id or ''):return False
        if paths.ledger.stat().st_size>131072:return False
        saved=json.loads(paths.ledger.read_text(encoding='utf-8'))
        if saved.get('schema_version')!=1 or saved.get('project_root')!=str(paths.project.resolve()) or saved.get('user_sid')!=paths.sid:return False
        group=saved['groups'][role]
        args=service_arguments(paths,role,owner,fixture=fixture)+['--attempt-id',attempt_id]
        if not fixture:args+=['--intent-generation',str(intent_generation)]
        return (group.get('attempt_id')==attempt_id and group.get('owner')==owner and group.get('admitted') is True
                and group.get('args')==args and group.get('pid')==identity['pid'] and group.get('created_at')==identity['created_at']
                and group.get('launcher_pid') in (os.getpid(),os.getppid())
                and group.get('launcher_created_at') is not None
                and process_created(group['launcher_pid'])==group['launcher_created_at'])
    except (OSError,ValueError,TypeError,KeyError):return False


def run_service(paths, role, owner, *, fixture=False,intent_generation=None,attempt_id=None):
    security=Security(paths.sid);lease=Mutex(lease_paths(paths,role).mutex,security)
    try:
        if lease.existing:return 2
        if not fixture:
            intent=IntentStore(paths)
            if (not intent.valid or not intent.value['enabled'] or intent_generation is None
                or not intent.value['start_generation']<=intent_generation<=intent.value['intent_generation']):return 3
        if not fixture and attempt_id is None:return 3
        return _run_service(paths,role,owner,fixture=fixture,intent_generation=intent_generation,attempt_id=attempt_id)
    finally:lease.close();security.close()


def _run_service(paths, role, owner, *, fixture=False,intent_generation=None,attempt_id=None):
    if not fixture:
        import json
        expected={"schema_version":1,"project_root":str(paths.project.resolve()),"user_sid":paths.sid,"approved":True}
        receipt=json.loads((paths.state_dir/"installation.json").read_text(encoding="utf-8"))
        if receipt!=expected:raise ValueError("managed production service is not installed/approved")
    stop = threading.Event()
    def stopped_by_intent():
        if fixture:return False
        intent=IntentStore(paths)
        return not intent.valid or not intent.value['enabled'] or not intent.value['start_generation']<=intent_generation<=intent.value['intent_generation']
    if stopped_by_intent():return 3
    def watch_intent():
        while not stop.wait(.2):
            if stopped_by_intent():stop.set();return
    if not fixture:threading.Thread(target=watch_intent,name='intent-guard',daemon=True).start()
    identity = {"service":role,"owner":owner,"pid":os.getpid(),"created_at":process_created(os.getpid()),'admitted':False}
    def dispatch(request):
        accepted = request["command"] in ("status","stop")
        if accepted and request["command"]=="stop":stop.set()
        return dict(schema_version=1,request_id=request["request_id"],accepted=accepted,**identity)
    pipe = PipeServer(service_paths(paths,role,owner),dispatch)
    pipe.start()
    try:
        if attempt_id is not None:
            deadline=time.monotonic()+30
            while not stop.is_set() and not stopped_by_intent():
                if admitted_launch(paths,role,owner,attempt_id,identity,fixture=fixture,intent_generation=intent_generation):break
                if time.monotonic()>=deadline:return 4
                stop.wait(.05)
            else:return 3
        if stop.is_set() or stopped_by_intent():return 3
        identity['admitted']=True
        if fixture:
            # It is an actual dedicated process/pipe with no production imports,
            # listeners, model/TTS calls or shared-service access.
            stop.wait(90)
        elif role=="voice":
            import asyncio
            import uvicorn
            from app.config import load_config
            cfg=load_config()
            server=uvicorn.Server(uvicorn.Config("app.main:app",host=cfg.server_host,
                                  port=cfg.server_port,log_level=cfg.log_level.lower()))
            def shutdown():stop.wait();server.should_exit=True
            threading.Thread(target=shutdown,daemon=True).start()
            asyncio.run(server.serve())
        elif role=="mdns":
            from .discovery import advertise
            advertise(paths,stop)
        elif role=="memory_service":
            import http.server
            original=http.server.ThreadingHTTPServer
            class ManagedServer(original):
                def __init__(self,*args,**kwargs):
                    super().__init__(*args,**kwargs)
                    def shutdown():stop.wait();self.shutdown()
                    threading.Thread(target=shutdown,daemon=True).start()
            # Only this newly created child process is patched, not the shared
            # memory source or any existing server. Its actual main/handlers run.
            http.server.ThreadingHTTPServer=ManagedServer
            script=__import__("pathlib").Path.home()/".hermes/scripts/memory_server.py"
            runpy.run_path(str(script),run_name="__main__")
        else:raise ValueError("unsupported fixed service role")
    finally:pipe.close()
    return 0
