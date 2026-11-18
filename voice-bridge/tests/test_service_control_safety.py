"""Control ownership and observation failures must remain fail-closed."""
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from service_control.identity import classify, component_identity
from service_control.paths import ControlPaths
from service_control.provider import WindowsProvider
from service_control.core import ControlCore
from service_control.state import SnapshotReader, atomic_json
from service_control.observations import observe_dependencies
from service_control.launch import parser, control_paths
from test_service_control_decisions import Provider, snapshot


def records(tmp_path):
    exe=tmp_path/'venv/Scripts/pythonw.exe';base=tmp_path/'base/pythonw.exe';script=tmp_path/'run.py'
    def record(pid,parent,image,birth):
        return dict(ProcessId=pid,ParentProcessId=parent,Name='pythonw.exe',ExecutablePath=str(image),
                    CommandLine=f'"{image}" "{script}"',CreatedAt=birth,UserSid='fixture-sid')
    return exe,base,script,[record(10,1,exe,50),record(11,10,base,51)]


def test_base_child_requires_exact_parent_chain(tmp_path):
    exe,base,script,rows=records(tmp_path)
    assert classify(rows[1],script,exe,rows,base=base,sid='fixture-sid')=='owned'
    assert classify(rows[1],script,exe,rows[1:],base=base,sid='fixture-sid')=='unknown'
    rows[0]['CommandLine']+=' --unrelated'
    assert classify(rows[1],script,exe,rows,base=base,sid='fixture-sid')=='unknown'


@pytest.mark.parametrize('key,value',[('CreatedAt',0),('CreatedAt',float('nan')),('CreatedAt',float('inf')),
                                    ('UserSid','other'),('ExecutablePath',None)])
def test_bad_identity_cannot_be_owned(tmp_path,key,value):
    exe,base,script,rows=records(tmp_path);rows[1][key]=value
    assert classify(rows[1],script,exe,rows,base=base,sid='fixture-sid')!='owned'


@pytest.mark.parametrize('birth',[0,-1,float('nan'),float('inf'),52])
def test_invalid_parent_birth_never_proves_chain(tmp_path,birth):
    exe,base,script,rows=records(tmp_path);rows[0]['CreatedAt']=birth
    assert classify(rows[1],script,exe,rows,base=base,sid='fixture-sid')=='unknown'


def test_relative_script_query_failure_and_other_listener_preserved(tmp_path):
    exe,base,script,rows=records(tmp_path)
    rows[1]['CommandLine']=f'"{base}" run.py'
    assert component_identity(rows,{11},script,exe,base=base,sid='fixture-sid')['state']=='UNKNOWN'
    assert component_identity(None,None,script,exe)['state']=='UNKNOWN'
    rows[1]['ExecutablePath']=str(tmp_path/'unrelated.exe')
    assert component_identity(rows,{11},script,exe,base=base,sid='fixture-sid')['state']=='CONFLICT'


def test_component_failure_does_not_block_other_components(tmp_path):
    class Failing(Provider):
        def start(self,name):
            if name=='voice':raise PermissionError('private fixture detail')
            return super().start(name)
    core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),Failing());core.check()
    assert core.state['components']['voice']['state']=='FAILED'
    assert core.state['components']['mdns']['state']=='READY'
    assert core.state['components']['memory_service']['state']=='READY'
    assert 'private fixture' not in json.dumps(core.state)


def test_verified_process_rows_complete_with_dependency_result(tmp_path):
    class Checking(Provider):
        def start(self,name):
            value=super().start(name)
            return dict(value,state='CHECKING',owner='created') if name!='voice' else value
    core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),Checking());core.check()
    assert core.state['components']['mdns']['state']=='READY'
    assert core.state['components']['memory_service']['lifecycle']=='HEALTHY_CREATED'


def test_120_second_startup_and_repeated_ensure_cannot_extend_deadline(tmp_path):
    class Starting(Provider):
        def inspect(self,name):return dict(state='STARTING',lifecycle='STARTING')
    now=[100.];core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),Starting(),clock=lambda:now[0])
    now[0]=219.;core.dispatch(dict(request_id='another',command='ensure'));core.check()
    assert core.state['components']['voice']['state']=='STARTING'
    now[0]=220.;core.check()
    assert core.state['components']['voice']['state']=='FAILED'


def test_publisher_enforces_startup_deadline_during_long_check(tmp_path):
    now=[100.];core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),Provider(),clock=lambda:now[0])
    core.state['components']['voice']=dict(state='STARTING',reason='fixture loading',last_check_at=100)
    security=SimpleNamespace(secure_file=lambda path:None)
    now[0]=220.;assert core.publish(security)
    state=json.loads(core.paths.snapshot.read_text(encoding='utf-8'))
    assert state['overall']=='FAILED' and state['components']['voice']['state']=='FAILED'


def test_recovery_attempt_is_saved_before_a_failed_start(tmp_path):
    class FailedStart(Provider):
        def __init__(self):super().__init__();self.saved=[]
        def inspect(self,name):return dict(state='FAILED',lifecycle='ABSENT')
        def persist_recovery(self):self.saved.append(dict(self.recovery_history))
        def start(self,name):raise OSError('fixture cannot spawn')
    provider=FailedStart();provider.groups['voice']=True
    core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),provider,clock=lambda:100.)
    core.failure_count['voice']=1
    with pytest.raises(OSError):core.check_component('voice')
    assert provider.saved==[{'voice':[100.]}]


def test_unreadable_installation_never_grants_start_or_stop(tmp_path):
    provider=WindowsProvider(ControlPaths(tmp_path,tmp_path,'fixture-sid'))
    assert not provider._receipt()
    (tmp_path/'installation.json').write_text('{',encoding='utf-8')
    assert not provider._receipt()
    assert provider.start('voice')['state']=='FAILED'
    with pytest.raises(ValueError):provider.stop('voice')


def test_possible_old_watchdog_without_commandline_blocks_migration(monkeypatch,tmp_path):
    provider=WindowsProvider(ControlPaths(tmp_path,tmp_path,'fixture-sid'))
    provider.records=[dict(ProcessId=10,Name='pythonw.exe',ExecutablePath=str(provider.python),CommandLine=None)]
    def forbidden(*a,**k):raise AssertionError('unknown manager must never be terminated')
    monkeypatch.setattr('service_control.provider.HeldProcess',forbidden)
    assert provider._migrate_watchdog()['state']=='CONFLICT'


def test_missing_modules_preflight_has_no_service_spawn(monkeypatch,tmp_path):
    paths=ControlPaths(tmp_path,tmp_path,'fixture');provider=WindowsProvider(paths);provider.can_manage=True
    exe=tmp_path/'pythonw.exe';exe.write_bytes(b'fixture');provider.python=exe
    monkeypatch.setattr('service_control.provider.subprocess.run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'["uvicorn"]'))
    def forbidden(*a,**k):raise AssertionError('no service spawn before valid preflight')
    monkeypatch.setattr('service_control.provider.subprocess.Popen',forbidden)
    assert 'uvicorn' in provider.start('voice')['reason'] and provider.groups=={}


def cfg(tmp_path):
    return SimpleNamespace(llm_api_server_url='http://127.0.0.1:8780/v1',memory_api_url='http://127.0.0.1:8781/api/v1/memory',
        llm_api_key=lambda:'fixture-secret',device_token=lambda:'fixture-device',lightweight_api_key=lambda:'fixture-light',
        user_profile_path=tmp_path/'USER.md',memory_file_path=tmp_path/'MEMORY.md',tts_primary='edge',tts_probe_interval_s=300)


def test_authentication_requires_verified_endpoint_processes(monkeypatch,tmp_path):
    calls=[]
    def get(url,**kw):
        calls.append((url,kw))
        if url.endswith('/health'):return dict(status='ok')
        if url.endswith('/models'):return dict(data=[])
        if url.endswith('/memory'):return dict(ok=True,facts='fixture-private')
        return dict(module_ready=True,hr_available=True,spo2_available=False,source_age_verified=True)
    monkeypatch.setattr('service_control.observations.get_json',get)
    monkeypatch.setattr('service_control.observations.adapters',lambda:[])
    paths=ControlPaths(tmp_path,tmp_path,'fixture');voice=dict(state='READY')
    value=observe_dependencies(cfg(tmp_path),paths,voice)
    assert len(calls)==1 and calls[0][1]=={} and value['hermes']['state']!='READY'
    calls.clear();value=observe_dependencies(cfg(tmp_path),paths,voice,gateway_identity=True,memory_identity=True,voice_identity=True)
    assert len(calls)==4 and value['data']['state']=='READY'
    assert 'fixture-secret' not in json.dumps(value) and 'fixture-private' not in json.dumps(value)


@pytest.mark.parametrize('url',['http://127.0.0.1:8780/wrong','http://user:secret@127.0.0.1:8780/v1','http://example.invalid:8780/v1'])
def test_wrong_gateway_configuration_has_no_authenticated_probe(monkeypatch,tmp_path,url):
    calls=[];value=cfg(tmp_path);value.llm_api_server_url=url
    monkeypatch.setattr('service_control.observations.get_json',lambda url,**kw:calls.append((url,kw)))
    monkeypatch.setattr('service_control.observations.adapters',lambda:[])
    observe_dependencies(value,ControlPaths(tmp_path,tmp_path,'fixture'),dict(state='READY'),gateway_identity=True)
    assert not calls


@pytest.mark.parametrize('tts',[{},[],dict(configured_primary='edge',active_engine='edge',last_probe_ok=True,last_probe_ts='broken')])
def test_bad_tts_snapshot_cannot_break_refresh_and_leave_green(tmp_path,tts):
    state=snapshot(tmp_path,'fixture');state['components']['voice']['tts']=tts
    path=tmp_path/'status.json';atomic_json(path,state);reader=SnapshotReader(tmp_path,'fixture')
    reader.verify_identity({key:state[key] for key in ('core_instance_id','core_pid','core_created_at')})
    assert reader.read(path,now=101)['overall']=='UNKNOWN'


def test_oversized_snapshot_is_unknown(tmp_path):
    path=tmp_path/'status.json';path.write_bytes(b' '* (128*1024+1))
    assert SnapshotReader(tmp_path,'fixture').read(path)['overall']=='UNKNOWN'


def test_invalid_cli_echoes_no_secret_and_production_scope_fixed(tmp_path):
    with pytest.raises(ValueError,match='invalid fixed control arguments'):parser().parse_args(['--arbitrary','fixture-secret'])
    with pytest.raises(ValueError):control_paths(parser().parse_args(['--namespace','test-other','--state-dir',str(tmp_path)]))


def test_failed_gui_runtime_has_persistent_native_feedback_without_private_error(monkeypatch):
    import ctypes,runpy
    from service_control.launch import PROJECT
    def failed(*args):raise RuntimeError('fixture-secret-private-error')
    messages=[]
    monkeypatch.setattr('service_control.launch.main',failed)
    monkeypatch.setattr(ctypes.windll.user32,'MessageBoxW',lambda *args:messages.append(args) or 1)
    with pytest.raises(SystemExit) as result:runpy.run_path(str(PROJECT/'voice-bridge/service_control_window.py'),run_name='__main__')
    assert result.value.code==1 and len(messages)==1
    assert 'RuntimeError' in messages[0][1] and 'README.md' in messages[0][1]
    assert 'fixture-secret' not in messages[0][1]


def test_network_change_unregisters_old_advertisement_before_new(monkeypatch,tmp_path):
    import sys
    from service_control.discovery import advertise
    events=[];addresses=iter(['192.168.1.2','192.168.1.3',None])
    class ZC:
        def __init__(self,interfaces):self.address=interfaces[0];events.append(('open',self.address))
        def register_service(self,info):events.append(('register',self.address))
        def unregister_service(self,info):events.append(('unregister',self.address))
        def close(self):events.append(('close',self.address))
    class Stop:
        count=0
        def is_set(self):return self.count==3
        def wait(self,seconds):assert seconds==5;self.count+=1
    monkeypatch.setitem(sys.modules,'zeroconf',SimpleNamespace(Zeroconf=ZC,ServiceInfo=lambda *a,**kw:kw))
    monkeypatch.setattr('service_control.discovery.adapters',lambda:next(addresses))
    monkeypatch.setattr('service_control.discovery.choose_lan',lambda address,selection:dict(selected=dict(address=address)) if address else {})
    advertise(ControlPaths(tmp_path,tmp_path,'fixture'),Stop())
    assert events==[('open','192.168.1.2'),('register','192.168.1.2'),('unregister','192.168.1.2'),('close','192.168.1.2'),
                    ('open','192.168.1.3'),('register','192.168.1.3'),('unregister','192.168.1.3'),('close','192.168.1.3')]


def test_native_query_failure_is_unknown_never_absent(monkeypatch):
    from service_control.processes import inventory
    def unavailable(*a,**kw):raise OSError('fixture native query unavailable')
    monkeypatch.setattr('service_control.processes.process_entries',unavailable)
    assert inventory()==(None,None)


def test_native_command_api_missing_never_proves_identity(monkeypatch):
    import os
    from service_control import windows
    monkeypatch.setattr(windows,'native_query',None)
    with pytest.raises(OSError,match='unavailable'):
        windows.native_process_record(os.getpid())


@pytest.mark.parametrize('size',[0,8,128*1024+1])
def test_native_command_bounds_rejected_before_dereference(monkeypatch,size):
    import ctypes as C
    from ctypes import wintypes as W
    from service_control import windows
    def bad_size(handle,kind,buffer,length,returned):
        C.cast(returned,C.POINTER(W.ULONG))[0]=size
        return -1073741820
    monkeypatch.setattr(windows,'native_query',bad_size)
    with pytest.raises(OSError,match='length unavailable'):
        windows._native_command(None)


def test_ipc_peer_parent_mismatch_is_rejected(monkeypatch):
    from service_control import processes
    sequence=iter([dict(ProcessId=100,ParentProcessId=101,CreatedAt=20),
                   dict(ProcessId=101,ParentProcessId=99,CreatedAt=30),
                   dict(ProcessId=100,ParentProcessId=101,CreatedAt=20)])
    monkeypatch.setattr(processes,'native_process_record',lambda pid:next(sequence))
    with pytest.raises(ValueError,match='parent'):
        processes.peer_record(100)


def test_recovery_reservation_precedes_stop_and_failed_start(tmp_path):
    now=[200.0];events=[]
    class FailingStart(Provider):
        def inspect(self,name):return dict(state='FAILED',lifecycle='ABSENT')
        def persist_recovery(self):events.append(('persist',list(self.recovery_history['voice'])))
        def stop(self,name):events.append(('stop',name));super().stop(name)
        def start(self,name):events.append(('start',name));raise OSError('synthetic failed start')
    provider=FailingStart();provider.groups['voice']=True
    core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),provider,clock=lambda:now[0])
    core.failure_count['voice']=1
    with pytest.raises(OSError):core.check_component('voice')
    assert events==[('persist',[200.0]),('stop','voice'),('start','voice')]
    assert not provider.created('voice') and core.recoveries['voice']==[200.0]
    core.dispatch(dict(request_id='manual-retry',command='retry'))
    now[0]=229.99;assert core.check_component('voice')['state']=='FAILED'
    assert len(events)==3
    now[0]=230
    with pytest.raises(OSError):core.check_component('voice')
    assert core.recoveries['voice']==[200.0,230]
    now[0]=260;assert core.check_component('voice')['state']=='FAILED'
    assert events[-2:]==[('persist',[200.0,230]),('start','voice')]


def test_failed_persistence_has_no_recovery_side_effect(tmp_path):
    calls=[]
    class NoPersist(Provider):
        def inspect(self,name):return dict(state='FAILED',lifecycle='ABSENT')
        def persist_recovery(self):raise OSError('synthetic write failure')
        def start(self,name):calls.append('start')
        def stop(self,name):calls.append('stop')
    provider=NoPersist();core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),provider,clock=lambda:200)
    core.recoveries['voice']=[150]
    with pytest.raises(OSError):core.check_component('voice')
    assert calls==[]


def test_empty_history_dead_group_recovery_persists_before_launch_and_restart(tmp_path,monkeypatch):
    from service_control.provider import WindowsProvider
    from service_control.state import atomic_json
    now=[100.];paths=ControlPaths(tmp_path,tmp_path,'synthetic-sid');events=[]
    monkeypatch.setattr('service_control.provider.time.monotonic',lambda:now[0])
    atomic_json(paths.ledger,dict(schema_version=1,project_root=str(tmp_path.resolve()),user_sid=paths.sid,
        recovery_history={},groups={'voice':dict(pid=999991,created_at=10,launcher_pid=999992,
            launcher_created_at=9,owner='a'*32)}))
    class LedgerProvider(Provider):
        def __init__(self):
            super().__init__();self.records=[];self.paths=paths;self.security=SimpleNamespace(secure_file=lambda p:None)
        def inspect(self,name):return dict(state='FAILED',lifecycle='ABSENT')
        def persist_recovery(self):WindowsProvider._save(self)
        def start(self,name):
            saved=json.loads(paths.ledger.read_text(encoding='utf-8'))
            events.append(saved['recovery_history'].get(name,[]));raise OSError('synthetic start failed')
    def reload():
        p=LedgerProvider();c=ControlCore(paths,p,clock=lambda:now[0]);WindowsProvider._load_ledger(p)
        assert p.groups=={}  # historical bookkeeping never grants stop rights
        return c
    core=reload()
    with pytest.raises(OSError):core.check_component('voice')
    assert events==[[100.]] and core.recoveries['voice']==[100.]
    now[0]=110.;core=reload();core.dispatch(dict(request_id='retry',command='retry'))
    assert core.check_component('voice')['state']=='FAILED' and len(events)==1
    now[0]=130.;core=reload()
    with pytest.raises(OSError):core.check_component('voice')
    assert events[-1]==[100.,130.]
    now[0]=160.;core=reload()
    assert core.check_component('voice')['state']=='FAILED' and len(events)==2


def test_initial_first_start_has_no_recovery_count_but_persists_managed_life(tmp_path):
    events=[]
    class Initial(Provider):
        def persist_recovery(self):events.append(('persist',set(self.managed_roles),dict(self.recovery_history)))
        def start(self,name):events.append(('start',name));return super().start(name)
    p=Initial();core=ControlCore(ControlPaths(tmp_path,tmp_path,'synthetic-sid'),p,clock=lambda:100.)
    assert core.check_component('voice')['state']=='READY'
    assert events==[('persist',{'voice'},{}),('start','voice')]


@pytest.mark.parametrize('status',['CHECKING','STOPPED'])
def test_legal_partial_nonready_snapshot_is_accepted(tmp_path,status):
    state=snapshot(tmp_path,'synthetic-sid');state.update(overall=status,components={})
    reader=SnapshotReader(tmp_path,'synthetic-sid');reader.verify_identity({k:state[k] for k in ('core_instance_id','core_pid','core_created_at')})
    path=tmp_path/'state.json';atomic_json(path,state)
    assert reader.read(path,now=101)['overall']==status and reader.sequence==state['snapshot_seq']


@pytest.mark.parametrize('missing',['voice','discovery','hermes','memory_read','memory','tts'])
def test_missing_ready_evidence_rejects_high_sequence_without_watermark(tmp_path,missing):
    import copy
    good=snapshot(tmp_path,'synthetic-sid');good['snapshot_seq']=7;bad=copy.deepcopy(good);bad['snapshot_seq']=1006
    if missing=='tts':del bad['components']['voice']['tts']
    else:del bad['components'][missing]
    reader=SnapshotReader(tmp_path,'synthetic-sid');reader.verify_identity({k:good[k] for k in ('core_instance_id','core_pid','core_created_at')})
    path=tmp_path/'state.json';atomic_json(path,bad)
    assert reader.read(path,now=101)['overall']=='UNKNOWN' and reader.sequence==-1
    atomic_json(path,good);assert reader.read(path,now=101)['overall']=='READY' and reader.sequence==7


def test_tts_expiry_boundary_and_fresh_heartbeat_do_not_extend_probe(tmp_path):
    state=snapshot(tmp_path,'synthetic-sid');state.update(updated_at=430)
    for component in state['components'].values():component['last_check_at']=430
    reader=SnapshotReader(tmp_path,'synthetic-sid');reader.verify_identity({k:state[k] for k in ('core_instance_id','core_pid','core_created_at')})
    path=tmp_path/'state.json';atomic_json(path,state)
    assert reader.read(path,now=430)['overall']=='READY'
    state.update(updated_at=431,snapshot_seq=2);atomic_json(path,state)
    value=reader.read(path,now=431)
    assert value['overall']=='UNKNOWN' and '探测过期' in value['reason'] and reader.sequence==1


@pytest.mark.parametrize('period',[None,True,0,-1,float('nan'),float('inf')])
def test_invalid_tts_period_never_produces_ready(period):
    from service_control.checks import voice_health
    body=dict(status='ok',asr='ready',device_auth='ok',tts=dict(configured_primary='edge',active_engine='edge',last_probe_ok=True,last_probe_ts=100))
    assert voice_health(body,'edge',period,now=101)['state']=='UNKNOWN'


@pytest.mark.parametrize('owned',[False,True])
def test_window_lease_selection_precedes_tk_and_duplicate_restores(monkeypatch,tmp_path,owned):
    from service_control import window
    events=[]
    class Security:
        def __init__(self,sid):events.append('security')
        def close(self):events.append('security-close')
    class Lease:
        def __init__(self,*args):events.append('lease')
        def acquire(self):events.append('acquire');return owned
        def close(self):events.append('lease-close')
    class FakeWindow:
        def __init__(self,*args,**kwargs):events.append('Tk');self.root=self
        def mainloop(self):events.append('loop')
        def close(self):events.append('window-close')
    monkeypatch.setattr(window,'Security',Security)
    monkeypatch.setattr(window,'Mutex',Lease)
    monkeypatch.setattr(window,'ControlWindow',FakeWindow)
    monkeypatch.setattr(window,'restore_window',lambda paths:events.append('restore'))
    monkeypatch.setattr(window,'connect_or_start',lambda *args:events.append('ensure'))
    assert window.show(ControlPaths(tmp_path,tmp_path,'fixture'),SimpleNamespace())==0
    assert events[:3]==['security','lease','acquire']
    if owned:assert events[3:]==['Tk','loop','window-close']
    else:assert events[3:]==['restore','ensure','lease-close','security-close'] and 'Tk' not in events


@pytest.mark.parametrize('status,allowed',[(0,True),(128,True),(258,False)])
def test_mutex_lease_uses_ownership_not_object_existence(monkeypatch,status,allowed):
    from service_control import windows
    lease=object.__new__(windows.Mutex);lease.handle=1;lease.owned=False;lease.existing=True
    monkeypatch.setattr(windows.k,'WaitForSingleObject',lambda *args:status)
    assert lease.acquire() is allowed
    assert lease.owned is allowed


def test_stopped_worker_sleeps_until_explicit_request(tmp_path):
    core=ControlCore(ControlPaths(tmp_path,tmp_path,'fixture'),Provider(),clock=lambda:100.)
    core.enabled=False;core.pending=False;timeouts=[]
    class Wake:
        def wait(self,timeout):timeouts.append(timeout);core.exit.set()
        def clear(self):pass
    core.wake=Wake();core.worker()
    assert timeouts==[None]


@pytest.mark.parametrize('stage',['header','body'])
def test_control_http_total_budget_even_when_peer_drips_bytes(stage):
    import socketserver,threading,time
    from service_control.observations import get_json
    stopped=threading.Event()
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(4096)
            try:
                if stage=='header':content=b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}';delay=.1
                else:
                    self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n')
                    content=b' '*100;delay=.05
                for char in content:
                    if stopped.wait(delay):break
                    self.request.sendall(bytes([char]))
            except OSError:pass
    class Server(socketserver.ThreadingTCPServer):daemon_threads=True
    with Server(('127.0.0.1',0),Handler) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        started=time.monotonic()
        try:
            result=get_json('http://127.0.0.1:'+str(server.server_address[1])+'/fixture')
            elapsed=time.monotonic()-started
            assert result is None and elapsed<3.5,(stage,elapsed)
        finally:stopped.set();server.shutdown();thread.join(2)


@pytest.mark.parametrize('field',['core_created_at','updated_at','round_elapsed_s','last_check_at',
                                 'last_probe_ts','probe_interval_s','probe_expires_at'])
@pytest.mark.parametrize('wide',[10**400,-10**400])
def test_unrepresentable_json_numeric_rejects_then_accepts_lower_valid_frame(tmp_path,field,wide):
    import copy
    good=snapshot(tmp_path,'synthetic-sid');good['snapshot_seq']=6
    reader=SnapshotReader(tmp_path,'synthetic-sid')
    reader.verify_identity({key:good[key] for key in ('core_instance_id','core_pid','core_created_at')})
    path=tmp_path/'state.json';atomic_json(path,good)
    assert reader.read(path,now=101)['overall']=='READY'
    bad=copy.deepcopy(good);bad['snapshot_seq']=1006
    if field in ('core_created_at','updated_at','round_elapsed_s'):bad[field]=wide
    elif field=='last_check_at':bad['components']['voice'][field]=wide
    else:bad['components']['voice']['tts'][field]=wide
    atomic_json(path,bad);out=reader.read(path,now=101)
    assert out['overall']=='UNKNOWN' and out['valid'] is False and reader.sequence==6
    good['snapshot_seq']=7;atomic_json(path,good)
    assert reader.read(path,now=101)['overall']=='READY' and reader.sequence==7


@pytest.mark.parametrize('status',['CHECKING','STARTING','READY','DEGRADED','FAILED','CONFLICT',
                                   'UNKNOWN','STOPPED','WAIT_NETWORK'])
@pytest.mark.parametrize('component',[None,True,0,'READY',[],[['state','READY'],['last_check_at',100]]])
def test_raw_component_types_never_normalize_or_commit_in_any_state(tmp_path,status,component):
    import copy
    good=snapshot(tmp_path,'synthetic-sid');good['snapshot_seq']=6
    reader=SnapshotReader(tmp_path,'synthetic-sid')
    reader.verify_identity({key:good[key] for key in ('core_instance_id','core_pid','core_created_at')})
    path=tmp_path/'state.json';atomic_json(path,good);assert reader.read(path,now=101)['overall']=='READY'
    bad=copy.deepcopy(good);bad.update(snapshot_seq=1006,overall=status);bad['components']['voice']=component
    atomic_json(path,bad);out=reader.read(path,now=101)
    assert out['overall']=='UNKNOWN' and out['valid'] is False and reader.sequence==6
    good['snapshot_seq']=7;atomic_json(path,good)
    assert reader.read(path,now=101)['overall']=='READY' and reader.sequence==7


@pytest.mark.parametrize('field',['last_probe_ts','probe_interval_s'])
@pytest.mark.parametrize('wide',[10**400,-10**400])
def test_producer_unrepresentable_numeric_returns_unknown_without_payload_overflow(field,wide):
    from service_control.checks import voice_health
    body=dict(status='ok',asr='ready',device_auth='ok',tts=dict(configured_primary='edge',
        active_engine='edge',last_probe_ok=True,last_probe_ts=100))
    period=300
    if field=='last_probe_ts':body['tts'][field]=wide
    else:period=wide
    out=voice_health(body,'edge',period,now=101)
    assert out['state']=='UNKNOWN'
    assert out['tts'][field] is None


def logical_refresh_view(tmp_path,monkeypatch):
    """Callback logic only; no Tk/native/process ownership proof."""
    import time
    from service_control import window
    state=snapshot(tmp_path,'synthetic-sid');state['updated_at']=time.time()
    for component in state['components'].values():component['last_check_at']=state['updated_at']
    state['components']['voice']['tts'].update(last_probe_ts=state['updated_at'],probe_expires_at=state['updated_at']+330)
    class Label:
        def __init__(self):self.text='READY'
        def configure(self,**values):self.text=values.get('text',self.text)
    view=object.__new__(window.ControlWindow);view.closed=False;view.connected=True;view.communication_error=None
    view.reader=SnapshotReader(tmp_path,'synthetic-sid')
    view.reader.verify_identity({key:state[key] for key in ('core_instance_id','core_pid','core_created_at')})
    view.paths=SimpleNamespace(snapshot=tmp_path/'state.json');view.options=SimpleNamespace(fixture=False)
    view.title=Label();view.progress=Label();view.tts=Label();view.checked=Label();view.rows={'voice':Label()}
    ticks=[];view.root=SimpleNamespace(after=lambda delay,callback:ticks.append(delay));view.last_verified=time.monotonic()
    monkeypatch.setattr(window,'process_created',lambda pid:state['core_created_at'])
    return view,state,ticks


@pytest.mark.parametrize('error_type',[OSError,ValueError,TypeError,OverflowError,KeyError,RecursionError])
def test_refresh_specific_input_failures_clear_green_and_keep_next_tick(tmp_path,monkeypatch,error_type):
    view,state,ticks=logical_refresh_view(tmp_path,monkeypatch)
    def bad_input(path):raise error_type('synthetic input failure')
    view.reader.read=bad_input;view.refresh()
    assert view.title.text.startswith('UNKNOWN') and not view.rows['voice'].text.startswith('READY')
    assert ticks==[1000]


def test_refresh_programming_errors_propagate_but_do_not_cancel_next_tick(tmp_path,monkeypatch):
    view,state,ticks=logical_refresh_view(tmp_path,monkeypatch)
    def bad_program(path):raise RuntimeError('programming sentinel')
    view.reader.read=bad_program
    with pytest.raises(RuntimeError,match='programming sentinel'):view.refresh()
    assert ticks==[1000]


def test_current_failed_probe_and_nonready_none_remain_legal_but_expiry_rejects(tmp_path):
    state=snapshot(tmp_path,'synthetic-sid');state.update(overall='DEGRADED',updated_at=430)
    for component in state['components'].values():component['last_check_at']=430
    state['components']['voice'].update(state='DEGRADED');state['components']['voice']['tts']['last_probe_ok']=False
    reader=SnapshotReader(tmp_path,'synthetic-sid')
    reader.verify_identity({key:state[key] for key in ('core_instance_id','core_pid','core_created_at')})
    path=tmp_path/'state.json';atomic_json(path,state)
    assert reader.read(path,now=430)['components']['voice']['state']=='DEGRADED'
    state.update(snapshot_seq=1006,updated_at=431);atomic_json(path,state)
    assert reader.read(path,now=431)['overall']=='UNKNOWN' and reader.sequence==1
    state.update(snapshot_seq=2,overall='UNKNOWN');state['components']['voice']['state']='UNKNOWN'
    state['components']['voice']['tts'].update(last_probe_ok=None,last_probe_ts=None,probe_expires_at=None)
    atomic_json(path,state);out=reader.read(path,now=431)
    assert out['overall']=='UNKNOWN' and out.get('valid',True) and reader.sequence==2
