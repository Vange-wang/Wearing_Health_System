"""Fixed local CLI dispatch; production and fixture roots cannot mix."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
import uuid
from .paths import ControlPaths
from .windows import current_sid, manager_exists
from .identity import invocation

PROJECT = Path(__file__).resolve().parents[2]
ENTRY = PROJECT/"voice-bridge/service_control.py"
PYTHONW = PROJECT/"voice-bridge/venv/Scripts/pythonw.exe"
REPORT_ROOT = PROJECT/"Code文档/测试报告/2026-10-12-服务启动重构"
NO_WINDOW = 0x08000000


def parser():
    class SafeParser(argparse.ArgumentParser):
        def error(self,message):raise ValueError("invalid fixed control arguments")
    value=SafeParser()
    value.add_argument("--core",action="store_true")
    value.add_argument("--window",action="store_true")
    value.add_argument('--autostart',action='store_true')
    value.add_argument("--service",choices=("voice","mdns","memory_service"))
    value.add_argument("--owner")
    value.add_argument('--intent-generation',type=int)
    value.add_argument('--attempt-id')
    value.add_argument("--command",choices=("ensure","status","retry","stop"),default="ensure")
    value.add_argument("--check-once",action="store_true")
    value.add_argument("--fixture",action="store_true")
    value.add_argument("--namespace",default="production")
    value.add_argument("--state-dir",type=Path)
    value.add_argument("--scenario",choices=("ready","no-lan","tts-failed"),default="ready")
    value.add_argument("--fixture-lifetime",type=float,default=90)
    value.add_argument("--fixture-window-lifetime",type=float)
    return value


def control_paths(options):
    if options.fixture:
        if not re.fullmatch(r"test-[a-z0-9-]{1,48}",options.namespace):raise ValueError("fixture namespace must be test-*")
        if options.state_dir is None:raise ValueError("fixture requires explicit report state directory")
        directory=options.state_dir.resolve()
        if not directory.is_relative_to(REPORT_ROOT.resolve()):raise ValueError("fixture writes must stay in the report directory")
        if not 5<=options.fixture_lifetime<=600:raise ValueError("fixture lifetime must be 5..600s")
    else:
        if options.namespace!="production" or options.state_dir is not None:
            raise ValueError("production scope is fixed")
        directory=PROJECT/"voice-bridge/logs/service-control"
    return ControlPaths(PROJECT,directory,current_sid(),options.namespace)


def core_arguments(options):
    args=["--core"]
    if options.fixture:
        args += ["--fixture","--namespace",options.namespace,"--state-dir",str(options.state_dir.resolve()),
                 "--scenario",options.scenario,"--fixture-lifetime",str(options.fixture_lifetime)]
    return args


def verified_control(paths, command, *, fixture=False, timeout=3, request_id=None):
    from .ipc import request
    from .processes import verify_peer
    reply,pid=request(paths,command,request_id or uuid.uuid4().hex,timeout=timeout)
    record=verify_peer(pid,paths,ENTRY,PYTHONW)
    call=invocation(record)
    options=parser().parse_args(call[2])
    peer_paths=control_paths(options)
    if not options.core or options.fixture!=fixture or peer_paths.scope!=paths.scope or peer_paths.state_dir!=paths.state_dir:
        raise ValueError("manager scope/role mismatch")
    identity=reply.get("identity")
    if not isinstance(identity,dict) or identity.get("core_pid")!=pid or identity.get("core_created_at")!=record["CreatedAt"]:
        raise ValueError("manager identity mismatch")
    return reply


def connect_or_start(paths, options):
    import subprocess
    try:return verified_control(paths,"ensure",fixture=options.fixture)
    except OSError:
        if manager_exists(paths.mutex):raise OSError("管理器存在但不可通信；保留服务，请查看日志")
    if options.fixture:
        subprocess.Popen([str(PYTHONW),str(ENTRY),*core_arguments(options)],cwd=PROJECT/"voice-bridge",creationflags=NO_WINDOW)
    else:
        from .task_host import start_verified_task
        start_verified_task(paths)
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        try:return verified_control(paths,"ensure",fixture=options.fixture,timeout=.5)
        except (OSError,TimeoutError):time.sleep(.1)
    raise TimeoutError("管理器启动后仍不可通信；未重复启动服务")


def main(argv=None):
    options=parser().parse_args(argv)
    paths=control_paths(options)
    if options.autostart:
        if options.fixture or options.core or options.window or options.service:raise ValueError('invalid autostart scope')
        from .task_host import start_verified_task
        start_verified_task(paths)  # no ensure: durable stop intent is preserved
        return 0
    if options.service:
        if not re.fullmatch(r"[0-9a-f]{32}",options.owner or ""):raise ValueError("fixed service requires owner UUID")
        from .service_host import run_service
        return run_service(paths,options.service,options.owner,fixture=options.fixture,intent_generation=options.intent_generation,attempt_id=options.attempt_id)
    if options.core:
        import logging
        from logging.handlers import RotatingFileHandler
        from .core import ControlCore
        from .provider import WindowsProvider, FixtureProvider
        paths.state_dir.mkdir(parents=True,exist_ok=True)
        from .windows import Security
        security=Security(paths.sid)
        try:security.secure_file(paths.state_dir)
        finally:security.close()
        handler=RotatingFileHandler(paths.state_dir/"control.log",maxBytes=1024*1024,backupCount=3,encoding="utf-8")
        logging.getLogger("voice-control").addHandler(handler)
        logging.getLogger("voice-control").setLevel(logging.INFO)
        provider=FixtureProvider(paths,options.scenario) if options.fixture else WindowsProvider(paths)
        try:return ControlCore(paths,provider).run(fixture_lifetime=options.fixture_lifetime if options.fixture else None)
        finally:handler.close()
    if options.window:
        import threading
        def submit():
            try:connect_or_start(paths,options)
            except (OSError,TimeoutError,ValueError):pass  # window/native feedback rechecks status
        request_thread=threading.Thread(target=submit,name='explicit-start-intent',daemon=False)
        request_thread.start();request_thread.join(.02)
        options.intent_dispatched=True
        from .window import show
        return show(paths,options)
    if options.command=="stop":
        print("请在状态窗口核对具体停止对象。")
        return 1
    reply=(connect_or_start(paths,options) if options.command=="ensure"
           else verified_control(paths,options.command,fixture=options.fixture))
    if options.check_once:
        receipt=reply.get('operation') or {}
        if receipt.get('state')=='interrupted':
            print(json.dumps({'accepted':True,'operation_state':'interrupted'},ensure_ascii=False));return 1
        target=receipt.get('sequence',reply['snapshot'].get('operation',{}).get('sequence'))
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            state=reply["snapshot"]
            operation=state.get('operation',{})
            if state["overall"] not in ("CHECKING","STARTING") and (target is None or operation.get('sequence',0)>=target and operation.get('state')=='completed'):
                print(json.dumps({"overall":state["overall"],"reason":state["reason"]},ensure_ascii=False))
                return 0 if state["overall"]=="READY" else 1
            time.sleep(2);reply=verified_control(paths,"status",fixture=options.fixture)
        print("启动未就绪（120秒）");return 1
    print(json.dumps({"accepted":reply["accepted"],"overall":reply["snapshot"]["overall"],"operation":reply.get('operation')},ensure_ascii=False))
    return 0 if reply["accepted"] else 1
