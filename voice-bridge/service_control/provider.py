"""Verified created groups and observed shared services, outside voice requests."""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
import ipaddress
import math
from .checks import result, voice_health
from .identity import component_identity, classify, invocation, normal
from .ipc import request
from .observations import get_json, observe_dependencies, selected_voice_health
from .processes import inventory, peer_record, verify_peer, HeldProcess, NO_WINDOW
from .state import atomic_json
from .windows import process_created
from .role_lease import handoff_verified
from .intent import IntentStore

ROLES = ("voice", "mdns", "memory_service")

# Isolated stdlib-only child. No env/key reads, shell, table flush or scan.
NEIGHBOR_HELPER = r'''
import ctypes as C,ipaddress,json,socket,sys
def main():
    target,source,subnet,intent_path,generation=sys.argv[1:]
    net=ipaddress.IPv4Network(subnet,strict=True);dst=ipaddress.IPv4Address(target);src=ipaddress.IPv4Address(source)
    if not 1<=net.prefixlen<=30 or src not in net or dst not in net or dst in (src,net.network_address,net.broadcast_address) or dst.is_loopback or dst.is_link_local or dst.is_multicast or int(dst)>>24 in (0,127) or int(dst)>=0xe0000000:raise ValueError()
    with open(intent_path,'rb') as handle:raw=handle.read(131073)
    if len(raw)>131072:raise ValueError()
    intent=json.loads(raw)
    if type(intent.get('schema_version')) is not int or intent.get('schema_version')!=1 or intent.get('enabled') is not True or type(intent.get('intent_generation')) is not int or intent['intent_generation']!=int(generation):
        return dict(schema_version=1,called=False,rc=0,length=0)
    send=C.WinDLL('iphlpapi.dll').SendARP
    send.argtypes=[C.c_uint32,C.c_uint32,C.c_void_p,C.POINTER(C.c_uint32)];send.restype=C.c_uint32
    buffer=(C.c_ubyte*8)();size=C.c_uint32(8)
    dest=C.c_uint32.from_buffer_copy(socket.inet_aton(target)).value
    own=C.c_uint32.from_buffer_copy(socket.inet_aton(source)).value
    rc=int(send(dest,own,C.byref(buffer),C.byref(size)))
    return dict(schema_version=1,called=True,rc=rc,length=int(size.value) if rc==0 else 0)
try:print(json.dumps(main(),separators=(',',':')))
except Exception:print('{"schema_version":1,"called":false,"rc":4294967295,"length":0}')
'''

def _neighbor_json(path):
    with path.open('rb') as source:raw=source.read(4097)
    if len(raw)>4096:raise ValueError('neighbor_state_size')
    return json.loads(raw)

def _neighbor_peer(value,source=None,subnet=None):
    if not isinstance(value,dict) or set(value)!={'schema_version','ipv4','subnet'} or type(value['schema_version']) is not int or value['schema_version']!=1:return None
    try:
        if type(value['ipv4']) is not str or type(value['subnet']) is not str:return None
        ip=ipaddress.IPv4Address(value['ipv4']);net=ipaddress.IPv4Network(value['subnet'],strict=True)
        if (not 1<=net.prefixlen<=30 or str(ip)!=value['ipv4'] or str(net)!=value['subnet'] or ip not in net
                or ip in (net.network_address,net.broadcast_address) or int(ip)>>24 in (0,127) or ip.is_link_local or int(ip)>=0xe0000000):return None
        if source is not None and (ip==ipaddress.IPv4Address(source) or ipaddress.IPv4Address(source) not in net or str(net)!=subnet):return None
        return dict(schema_version=1,ipv4=str(ip),subnet=str(net))
    except (ValueError,TypeError):return None

def _neighbor_budget(path,now):
    if type(now) not in (int,float) or not math.isfinite(now) or now<0:raise ValueError('neighbor_budget_clock')
    try:value=_neighbor_json(path)
    except FileNotFoundError:return []
    if (not isinstance(value,dict) or set(value)!={'schema_version','attempted_at'} or type(value['schema_version']) is not int or value['schema_version']!=1
            or type(value['attempted_at']) is not list or len(value['attempted_at'])>3):raise ValueError('neighbor_budget_invalid')
    stamps=value['attempted_at']
    if any(type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=now for t in stamps) or stamps!=sorted(stamps):raise ValueError('neighbor_budget_clock')
    return [t for t in stamps if now-t<60]


def public_tts_expectation(path):
    """Refresh public expectations only; never reload env/credential sources."""
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tts"), dict):
        raise ValueError("public TTS configuration missing")
    tts = data["tts"]
    primary = tts.get("primary")
    interval = tts.get("probe_interval_s", 300)
    if primary not in ("edge", "mimo") or type(primary) is not str:
        raise ValueError("public TTS primary invalid")
    if type(interval) is not int or not 1 <= interval <= 86400:
        raise ValueError("public TTS probe interval invalid")
    return primary, interval


def service_paths(paths, role, owner):
    return replace(paths,namespace=paths.namespace+"-"+role+"-"+owner)


def service_arguments(paths, role, owner, *, fixture=False):
    args = ["--service",role,"--owner",owner]
    if fixture:args += ["--fixture","--namespace",paths.namespace,"--state-dir",str(paths.state_dir.resolve())]
    return args


class WindowsProvider:
    can_manage = False

    def _stage(self,value):getattr(self,'report_stage',lambda text:None)(value)

    def dependency_requirements(self,role):
        if role=='mdns':return ['zeroconf']
        if role=='memory_service':return ['http','json']
        # Shared application modules import edge_tts symbols at module scope,
        # even with MiMo selected. Check presence only, never import an engine.
        names=['fastapi','uvicorn','yaml','numpy','httpx','aiohttp','certifi','edge_tts']
        cfg=self.cfg;asr=getattr(cfg,'asr_engine','sherpa')
        v2=getattr(cfg,'voice_v2_asr_engine','configured') if getattr(cfg,'voice_v2_enabled',False) else 'configured'
        if asr!='mimo' or v2=='sensevoice':names.append('sherpa_onnx')
        if getattr(cfg,'tts_primary','edge')=='edge':names.append('miniaudio')
        return names

    def dependency_preflight(self,role,executable):
        self._stage(role+':dependency_presence')
        modules=self.dependency_requirements(role)
        code="import importlib.util,json\nnames="+repr(modules)+"\ntry:\n missing=[name for name in names if importlib.util.find_spec(name) is None]\n print(json.dumps({'missing':missing}))\nexcept Exception:\n print(json.dumps({'error':'lookup_failed'}))"
        def failed(kind,reason,**extra):
            return result('FAILED',reason,lifecycle='ABSENT',fault_kind=kind,spawn_attempted=False,**extra)
        try:
            probe=subprocess.run([str(executable.with_name('python.exe')),'-B','-c',code],capture_output=True,timeout=8,creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return failed('dependency_probe_timeout','依赖存在性检查超时；未判定模块缺失')
        except OSError:
            return failed('dependency_probe_os_failure','依赖存在性检查无法运行；未判定模块缺失')
        if probe.returncode!=0:return failed('dependency_probe_exit','依赖存在性检查进程失败；未判定模块缺失',probe_exit_code=probe.returncode)
        try:
            if len(probe.stdout)>8192:raise ValueError()
            body=json.loads(probe.stdout.decode('utf-8-sig'))
            if body=={'error':'lookup_failed'}:return failed('dependency_probe_lookup','依赖规格查询失败；未判定模块缺失')
            missing=body['missing']
            if (set(body)!={'missing'} or not isinstance(missing,list) or len(missing)>len(modules)
                    or any(type(name) is not str or name not in modules for name in missing) or len(set(missing))!=len(missing)):raise ValueError()
        except (ValueError,TypeError,KeyError,UnicodeError):return failed('dependency_probe_invalid_output','依赖检查输出无效；未判定模块缺失')
        if missing:return failed('dependency_missing','依赖模块未发现：'+', '.join(missing),missing=missing)
        return None

    def __init__(self, paths):
        self.paths = paths
        self.voice_dir = paths.project / "voice-bridge"
        self.entry = self.voice_dir / "service_control.py"
        self.python = self.voice_dir / "venv/Scripts/pythonw.exe"
        self.conda = Path("D:/miniconda/pythonw.exe")
        self.memory_script = Path.home()/".hermes/scripts/memory_server.py"
        self.records = self.listeners = None
        self.groups = {}
        self.owner = None
        self.security = None
        self.cfg = None
        self.ledger_loaded = False
        self.migration_done = False
        self.fixture = False
        self.observed = {}
        self.unresolved_roles=set()
        self.recovery_history = {}
        self.managed_roles=set()
        self._box_evidence=None;self._box_evidence_at=0;self._neighbor_busy=False;self._neighbor_child=None

    def _receipt(self):
        # Installation is a separately reviewed step. Staged core code cannot
        # silently acquire production startup/stop authority during development.
        try:
            receipt=json.loads((self.paths.state_dir/"installation.json").read_text(encoding="utf-8"))
            return receipt == {"schema_version":1,"project_root":str(self.paths.project.resolve()),
                               "user_sid":self.paths.sid,"approved":True}
        except (OSError,ValueError):return False

    def begin(self):
        self._stage('configuration_receipt')
        self.can_manage = self._receipt()
        try:
            primary, interval = public_tts_expectation(self.voice_dir / "config.yaml")
            if self.cfg is None:
                from app.config import load_config
                self.cfg=load_config()
            self.cfg.tts_primary = primary
            self.cfg.tts_probe_interval_s = interval
        except Exception:
            return result("FAILED","公开TTS配置无效或现有配置无法加载；查看排查手册")
        self._stage('native_inventory');self.records,self.listeners=inventory()
        if self.records is None or self.listeners is None:
            return result("UNKNOWN","进程或端口查询失败，不能认定不存在")
        if not self.ledger_loaded:
            self._load_ledger();self.ledger_loaded=True
        if self.can_manage and not self.migration_done:
            old=self._migrate_watchdog()
            if old is not None:return old
            self.migration_done=True
        return None

    def _executable(self, role):
        return self.conda if role=="memory_service" else self.python

    def _args(self, role, owner):
        return service_arguments(self.paths,role,owner,fixture=self.fixture)

    def _load_ledger(self):
        try:
            saved=json.loads(self.paths.ledger.read_text(encoding="utf-8"))
            if saved.get("schema_version")!=1 or saved.get("project_root")!=str(self.paths.project.resolve()) or saved.get("user_sid")!=self.paths.sid:
                return
            managed=getattr(self,'managed_roles',None)
            if managed is None:self.managed_roles=managed=set()
            recorded=saved.get('managed_roles',[])
            if isinstance(recorded,list) and len(recorded)<=len(ROLES):
                managed.update(name for name in recorded if name in ROLES)
            for name,stamps in saved.get("recovery_history",{}).items():
                if name in ROLES and isinstance(stamps,list) and stamps:
                    now=time.monotonic();boot=saved.get('recovery_boot')
                    if type(boot) not in (int,float) or abs((time.time()-now)-boot)>5:
                        self.recovery_history[name]=[now,now]  # conservative 5min after unprovable boot continuity
                    elif all(type(value) in (int,float) and 0<=value<=now for value in stamps):
                        self.recovery_history[name]=[value for value in stamps if now-value<300][-2:]
                    else:self.recovery_history[name]=[now,now]
            for role, item in saved.get("groups",{}).items():
                if role not in ROLES or not isinstance(item,dict) or not re.fullmatch(r"[0-9a-f]{32}",str(item.get("owner",""))):continue
                # Legacy ledgers also establish prior managed accounting. No
                # handle/groups rights follow until full live identity passes.
                managed.add(role)
                expected_args=self._args(role,item['owner'])
                attempt=item.get('attempt_id')
                if attempt is not None:
                    if not re.fullmatch(r'[0-9a-f]{32}',str(attempt)):
                        self.unresolved_roles.add(role);continue
                    expected_args += ['--attempt-id',attempt]
                if 'intent_generation' in item and not self.fixture:
                    if type(item['intent_generation']) is not int or item['intent_generation']<0:
                        self.unresolved_roles.add(role);continue
                    expected_args += ['--intent-generation',str(item['intent_generation'])]
                if item.get('args',expected_args)!=expected_args:
                    self.unresolved_roles.add(role);continue
                if attempt is not None:
                    # A durable pre-spawn attempt is recoverable even if the
                    # previous core died before recording the launcher PID.
                    self.groups[role]=dict(item,handle=None,launcher=None,ledger_saved=True)
                    continue
                record=next((r for r in self.records if r["ProcessId"]==item.get("pid")),None)
                parent=next((r for r in self.records if r["ProcessId"]==item.get("launcher_pid")),None)
                if (record is None or parent is None or record.get("CreatedAt")!=item.get("created_at")
                        or parent.get("CreatedAt")!=item.get("launcher_created_at")
                        or invocation(record) is None or invocation(record)[2]!=expected_args
                        or classify(record,self.entry,self._executable(role),self.records,sid=self.paths.sid)!="owned"):
                    if record is not None and record.get('CreatedAt') in (None,item.get('created_at')):self.unresolved_roles.add(role)
                    continue
                self.groups[role]=dict(item,handle=HeldProcess(record,sid=self.paths.sid),launcher=None,ledger_saved=True)
        except (OSError,ValueError,TypeError,AttributeError):
            if self.paths.ledger.exists():self.unresolved_roles.update(ROLES)

    def _save(self):
        groups={}
        for name,entry in self.groups.items():
            groups[name]={key:entry[key] for key in ("pid","created_at","launcher_pid","launcher_created_at","owner","started_at","args","intent_generation","attempt_id","admitted") if key in entry}
        atomic_json(self.paths.ledger,dict(schema_version=1,project_root=str(self.paths.project.resolve()),
                    user_sid=self.paths.sid,groups=groups,recovery_history=self.recovery_history,recovery_boot=time.time()-time.monotonic(),
                    managed_roles=sorted(self.managed_roles & set(ROLES))),secure=self.security.secure_file)

    def _migrate_watchdog(self):
        if handoff_verified(self.paths):return None  # explicit Root handoff already completed
        script=self.voice_dir/"voice-bridge-watchdog.pyw"
        matches=[]
        for record in self.records:
            call=invocation(record)
            if call is None:
                if classify(record,script,self.python,self.records,sid=self.paths.sid)=='unknown':
                    return result('CONFLICT','可能存在旧守护但元数据不可读；保留且不启动第二恢复器')
                continue
            if Path(call[1]).name.lower()==script.name.lower():
                state=classify(record,script,self.python,self.records,sid=self.paths.sid)
                if state!="owned":return result("CONFLICT","旧守护身份不充分，保留进程且不启动第二恢复器")
                matches.append(record)
        # Stop verified old manager handles only. Its voice/mDNS/memory children
        # are deliberately not traversed, terminated or assigned created rights.
        # Only already verified watchdog matches participate in this graph.
        # Stop each verified child before its matched launcher; never discover
        # or grant rights to unrelated voice/mDNS/memory descendants.
        pending={}
        for record in matches:
            pid,parent=record.get("ProcessId"),record.get("ParentProcessId")
            if (type(pid) is not int or pid<=0 or type(parent) is not int or parent<0
                    or pid in pending):
                return result("CONFLICT","旧守护记录或排序不可信，保留现场")
            pending[pid]=record
        ordered=[]
        for _ in range(len(matches)):
            if not pending:break
            parents={record["ParentProcessId"] for record in pending.values()}
            leaves=[record for pid,record in pending.items() if pid not in parents]
            if not leaves:return result("CONFLICT","旧守护父子顺序存在冲突，保留现场")
            for record in leaves:
                ordered.append(record);del pending[record["ProcessId"]]
        if pending:return result("CONFLICT","旧守护父子顺序未核验，保留现场")
        handles=[]
        try:
            for record in ordered:handles.append(HeldProcess(record,sid=self.paths.sid))
            for handle in handles:handle.terminate()
        except (OSError,ValueError,TimeoutError):return result("CONFLICT","旧守护停止未核验，保留现场")
        finally:
            for handle in handles:handle.close()
        return None

    def persist_recovery(self):
        self._save()

    def created(self, role):return role in self.groups

    def created_summary(self):
        return [dict(name=name,pid=item.get("pid",item.get("launcher_pid")),created_at=item.get("created_at"),
                     verified=bool(item.get("handle") and item["handle"].alive()),owner="created")
                for name,item in list(self.groups.items())]

    def inspect(self, role):
        value=self._inspect(role)
        self.observed[role]=value
        return value

    def _bind_created(self, role, group):
        """Verify an existing attempt for admission OR cleanup; never spawn."""
        owner=group.get('owner',getattr(self,'owner',None))
        try:
            self._stage(role+':bind_peer')
            launcher=group.get('launcher')
            if launcher is not None and group.get('launcher_created_at') is not None:
                if process_created(launcher.pid)!=group['launcher_created_at']:return False
            reply,pid=request(service_paths(self.paths,role,owner),'status',uuid.uuid4().hex,timeout=.3)
            record=verify_peer(pid,self.paths,self.entry,self._executable(role),required_args=group.get('args',self._args(role,owner)))
            if reply.get('service')!=role or reply.get('owner')!=owner:return False
            if group.get('attempt_id') is not None:
                candidate=group.get('launcher_pid')
                if candidate is not None and candidate not in (pid,record.get('ParentProcessId')):return False
                if candidate is None:
                    candidate=pid if normal(record['ExecutablePath'])==normal(self._executable(role)) else record['ParentProcessId']
                birth=process_created(candidate)
                if birth is None or group.get('launcher_created_at',birth)!=birth:return False
                group.update(launcher_pid=candidate,launcher_created_at=birth)
            group.update(pid=pid,created_at=record['CreatedAt'],handle=HeldProcess(record,sid=self.paths.sid))
            # Disabled permits exact verification/stop, but never new admission.
            if group.get('attempt_id') is not None and getattr(self,'start_permitted',lambda generation=None:True)(group.get('intent_generation')):
                group['admitted']=True
            try:self._save();group['ledger_saved']=True
            except OSError:group['ledger_saved']=False
            self.records,self.listeners=inventory()
            return True
        except (OSError,TimeoutError,ValueError,TypeError,AttributeError):return False

    def _attempt_exited(self,role,group):
        launcher=group.get('launcher')
        if launcher is not None:return launcher.poll() is not None
        if self.records is None:return False
        expected=group.get('args')
        for record in self.records:
            call=invocation(record)
            if call is not None and call[2]==expected:return False
            if classify(record,self.entry,self._executable(role),self.records,sid=self.paths.sid)=='unknown':return False
            if record.get('ProcessId')==group.get('launcher_pid') and record.get('CreatedAt') in (None,group.get('launcher_created_at')):return False
        return True  # complete fresh inventory, no remaining candidate

    def _inspect(self, role):
        group=self.groups.get(role)
        if group:
            handle=group.get("handle")
            if handle is None:
                launcher=group.get("launcher")
                if launcher is not None and launcher.poll() is not None:
                    return result("FAILED","已创建启动器退出",lifecycle="ABSENT",owner="created")
                if not self._bind_created(role,group):
                    if group.get('attempt_id') is not None and self._attempt_exited(role,group):
                        return result('FAILED','完整查询确认启动尝试已退出',lifecycle='ABSENT',owner='created')
                    return result("STARTING","子进程归属或账本待核验；不重复创建",lifecycle="STARTING",owner="created",
                                  startup_at=group.get('started_at'),fault_kind='binding_pending')
                return self._inspect(role)
            port={"voice":8710,"mdns":None,"memory_service":8781}[role]
            owners={int(row["OwningProcess"]) for row in self.listeners or [] if row["LocalPort"]==port}
            if owners and owners!={group.get("pid")}:
                return result("CONFLICT","监听端口另有owner；保留所有进程",owner="created")
            if not handle.alive():return result("FAILED","已创建进程确已退出",lifecycle="ABSENT",owner="created")
            try:handle.verify()
            except (OSError,ValueError):return result("UNKNOWN","created身份重验失败，保留进程",owner="created")
            if not group.get("ledger_saved"):
                try:self._save();group["ledger_saved"]=True
                except OSError:return result("UNKNOWN","启动记录未保存，保留句柄且不重复创建",owner="created")
            identity=dict(state="VERIFIED",pid=group["pid"],created_at=group["created_at"],
                          executable=str(self._executable(role)),script=str(self.entry),owner="created")
        else:
            if role in getattr(self,'unresolved_roles',set()):return result('UNKNOWN','旧owned账本归属未闭合；保留且不重复创建')
            for record in self.records or []:
                call=invocation(record)
                if call is None or not Path(call[1]).is_absolute() or normal(call[1])!=normal(self.entry):continue
                args=call[2]
                if args[:2]==["--service",role]:
                    return result("UNKNOWN","存在同项目托管服务但账本未核验；保留且不重复创建")
            script={"voice":self.voice_dir/"run.py","mdns":self.voice_dir/"mdns_advertise.py","memory_service":self.memory_script}[role]
            ports={"voice":8710,"mdns":None,"memory_service":8781}
            pids={int(item["OwningProcess"]) for item in self.listeners or [] if item["LocalPort"]==ports[role]}
            executable=self._executable(role)
            choices=[component_identity(self.records,pids,script,variant,sid=self.paths.sid)
                     for variant in (executable,executable.with_name("python.exe"))]
            identity=next((value for value in choices if value["state"]=="VERIFIED"),None)
            if identity is None:
                identity=next((value for value in choices if value["state"]=="UNKNOWN"),choices[0])
            if identity["state"]=="ABSENT":return result("FAILED","完整查询确认不存在",lifecycle="ABSENT",owner="absent")
            if identity["state"]!="VERIFIED":return dict(identity,last_check_at=None)
            identity["owner"]="reused"
        if role=="voice":
            self._stage('voice:authenticated_health')
            self._box_evidence_at=time.monotonic()
            body=selected_voice_health(self.cfg,"http://127.0.0.1:8710")
            self._box_evidence={key:body.get(key) for key in ('pc_instance','box_link','discovery_udp')} if isinstance(body,dict) else None
            health=voice_health(body,self.cfg.tts_primary,self.cfg.tts_probe_interval_s)
            # A newly created server may still be in ASR/model lifespan startup.
            if body is None and identity["owner"]=="created":health=result("STARTING","模型/服务尚未完成启动")
            if identity["owner"]=="created" and not owners:health=result("STARTING","创建进程在运行，监听归属尚未确认",fault_kind='local_no_listener')
            elif body is None and identity['owner']=='created':health['fault_kind']='local_no_http'
        elif role=="memory_service":
            health=result("CHECKING","记忆只读鉴权将在依赖步骤核验")
        else:health=result("CHECKING","mDNS广告将在LAN步骤核验")
        healthy=health["state"]=="READY"
        return dict(health,**{key:value for key,value in identity.items() if key!="state" and key!="reason"},
                    lifecycle=("HEALTHY_" if healthy else "UNHEALTHY_")+identity["owner"].upper(),
                    startup_at=group.get('started_at') if group else None)

    def start(self, role):
        if not self.can_manage:return result("FAILED","候选仅观察；正式安装前不启动服务",lifecycle="ABSENT")
        if role in self.groups:return self.inspect(role)
        generation=getattr(self,'intent_generation',lambda:0)()
        if not getattr(self,'start_permitted',lambda generation=None:True)(generation):
            return result('STOPPED','停止意图阻止旧代启动',lifecycle='ABSENT')
        executable=self._executable(role)
        if not executable.is_file():return result("FAILED","解释器缺失："+str(executable),lifecycle="ABSENT")
        if not self.fixture:
            failure=self.dependency_preflight(role,executable)
            if failure is not None:return failure
            if role=="memory_service" and not self.memory_script.is_file():return result("FAILED","既有memory脚本缺失",lifecycle="ABSENT")
        attempt=uuid.uuid4().hex
        args=self._args(role,self.owner)+['--attempt-id',attempt]
        if not self.fixture:args += ['--intent-generation',str(generation)]
        self.paths.state_dir.mkdir(parents=True,exist_ok=True)
        log_file=(self.paths.state_dir/(role+"-managed.log")).open("ab")
        env=os.environ.copy();env["PYTHONIOENCODING"]="utf-8";env["PYTHONDONTWRITEBYTECODE"]="1"
        if role=="memory_service" and self.cfg and self.cfg.llm_api_key():env["API_SERVER_KEY"]=self.cfg.llm_api_key()
        try:
            import contextlib
            self._stage(role+':spawn')
            with getattr(self,'launch_lock',contextlib.nullcontext()):
                if not getattr(self,'start_permitted',lambda generation=None:True)(generation):
                    return result('STOPPED','停止意图阻止旧代启动',lifecycle='ABSENT')
                self.groups[role]=dict(owner=self.owner,started_at=time.monotonic(),intent_generation=generation,
                                       attempt_id=attempt,args=args,admitted=False,ledger_saved=False)
                self._save()  # pre-spawn durable attempt; child cannot import business yet
                launcher=subprocess.Popen([str(executable),str(self.entry),*args],cwd=self.voice_dir,env=env,
                                          stdout=log_file,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
                self.groups[role].update(launcher=launcher,launcher_pid=launcher.pid,launcher_created_at=process_created(launcher.pid))
                self._save()  # durable launcher identity BEFORE the first pipe request
        finally:log_file.close()
        entry=self.groups[role]
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and launcher.poll() is None:
            if not getattr(self,'start_permitted',lambda generation=None:True)(generation):
                return result('STARTING','新停止意图已生效，保留待核验启动器',lifecycle='STARTING',owner='created')
            if self._bind_created(role,entry):return self.inspect(role)
            time.sleep(.1)
        return result("STARTING","启动器已创建；子进程未就绪/归属待核验",lifecycle="STARTING",owner="created")

    def stop(self, role):
        if not self.can_manage:raise ValueError("candidate has no production stop authority")
        entry=self.groups.get(role)
        if entry is None:return
        handle=entry.get("handle")
        if handle is None:
            self._bind_created(role,entry)  # cleanup verification does not grant launch permission
            handle=entry.get('handle')
            if handle is None:self.records,self.listeners=inventory()
            if handle is None and self._attempt_exited(role,entry):
                # The held Popen launcher is the exact owned attempt. Verified
                # venv redirector lifetime tests establish it waits for its child.
                self.groups.pop(role);self._save();return
            if handle is None:raise ValueError("created group has no verified child handle")
        if handle.alive():
            handle.verify()
            try:
                _,peer=request(service_paths(self.paths,role,entry["owner"]),"stop",uuid.uuid4().hex,timeout=1)
                if peer!=handle.pid:raise ValueError("graceful-stop peer changed")
            except (OSError,TimeoutError):pass
            deadline=time.monotonic()+10
            while handle.alive() and time.monotonic()<deadline:time.sleep(.05)
            if handle.alive():handle.terminate()
        handle.close();self.groups.pop(role)
        self._save()

    def dependencies(self, voice):
        self._stage('readonly_dependencies')
        gateway_identity=True
        gateway_listeners=[r for r in self.listeners or [] if r["LocalPort"]==8780]
        if not gateway_listeners:gateway_identity=False
        for listener in gateway_listeners:
            record=next((r for r in self.records if r["ProcessId"]==listener["OwningProcess"]),None)
            call=invocation(record) if record else None
            if (record is None or record.get("UserSid")!=self.paths.sid or not record.get("CreatedAt")
                    or normal(record.get("ExecutablePath") or "") not in (normal(self.conda),normal(self.conda.with_name("python.exe")))
                    or call is None or call[1]!="-m" or call[2]!=["hermes_cli.main","gateway","run"]):
                gateway_identity=False
        memory=self.observed.get("memory_service",{})
        memory_identity=memory.get("owner") in ("created","reused") and memory.get("pid") is not None and memory.get("state") not in ("CONFLICT","UNKNOWN","FAILED")
        voice_identity=voice.get("owner") in ("created","reused") and voice.get("pid") is not None and voice.get("state")!="CONFLICT"
        values=observe_dependencies(self.cfg,self.paths,voice,gateway_identity=gateway_identity,
                                    memory_identity=memory_identity,voice_identity=voice_identity)
        for port,name in [(8780,"hermes"),(8781,"memory")]:
            listeners=[item for item in self.listeners or [] if item["LocalPort"]==port]
            if not listeners:
                values[name]=dict(values[name],state="DEGRADED",reason="共享服务监听缺失/尚在启动")
        if memory.get("state") in ("CONFLICT","UNKNOWN","FAILED"):
            values["memory"]=result(memory["state"],"记忆服务进程归属未通过")
        # Gateway must match the known shared invocation before health/auth can
        # imply a usable tool dependency. It is never created/stopped here.
        for listener in self.listeners or []:
            if listener["LocalPort"]!=8780:continue
            record=next((r for r in self.records if r["ProcessId"]==listener["OwningProcess"]),None)
            call=invocation(record) if record else None
            if (record is None or record.get("UserSid")!=self.paths.sid or not record.get("CreatedAt")
                    or normal(record.get("ExecutablePath") or "") not in (normal(self.conda),normal(self.conda.with_name("python.exe")))
                    or call is None or call[1]!="-m" or call[2]!=["hermes_cli.main","gateway","run"]):
                values["hermes"]=result("UNKNOWN","共享Hermes进程身份未核验")
        link=values.get('box_link')
        if isinstance(link,dict):
            values['box_link']=dict(link,neighbor_recovery=self._box_neighbor(voice,values))
        return values

    def _neighbor_permitted(self,generation):
        permitted=getattr(self,'start_permitted',None)
        if not self.can_manage or self.fixture or not callable(permitted) or not permitted(generation):return False
        saved=IntentStore(self.paths,fixture=False)
        return saved.valid and type(saved.value.get('schema_version')) is int and saved.value['enabled'] and saved.value['intent_generation']==generation

    def _box_neighbor(self,voice,values):
        def report(category,**fields):return dict(category=category,attempted=False,**fields)
        security=getattr(self,'security',None);lock=getattr(self,'launch_lock',None)
        generation=getattr(self,'intent_generation',lambda:None)()
        if (type(generation) is not int or lock is None or security is None or not self._neighbor_permitted(generation)):
            return report('DISABLED')
        if voice.get('state')!='READY' or voice.get('owner') not in ('created','reused') or voice.get('pid') is None:return report('VOICE_NOT_READY')
        body=getattr(self,'_box_evidence',None);elapsed=time.monotonic()-getattr(self,'_box_evidence_at',0)
        discovery=values.get('discovery',{});udp=body.get('discovery_udp') if isinstance(body,dict) else None
        selected=discovery.get('selected');network=udp.get('selected_subnet') if isinstance(udp,dict) else None
        if (not 0<=elapsed<=30 or not isinstance(selected,dict) or not isinstance(network,dict) or discovery.get('lan_state')!='READY'
                or values.get('udp_discovery',{}).get('state')!='READY' or udp.get('listener')!='LISTENING'
                or type(selected.get('index')) is not int or selected['index']<=0 or selected.get('address')!=network.get('address')):return report('NETWORK_NOT_READY')
        source=network['address'];subnet=network.get('network')
        try:
            from .native_adapters import adapters
            from .checks import choose_lan
            rows=adapters();fresh=choose_lan(rows,selected.get('index'))
            exact=[r for r in rows if r.get('index')==selected.get('index') and r.get('address')==source]
            if fresh.get('state')!='READY' or fresh['selected']['address']!=source or len(exact)!=1:raise ValueError()
            prefix=exact[0].get('prefix_length')
            if type(prefix) is not int or not 1<=prefix<=30 or str(ipaddress.IPv4Network((source,prefix),strict=False))!=subnet:raise ValueError()
        except (OSError,ValueError,TypeError,KeyError):return report('NETWORK_CHANGED')
        peer_path=self.paths.state_dir/'box-peer.json';budget_path=self.paths.state_dir/'box-neighbor-budget.json'
        link=body.get('box_link');observed=values.get('box_link',{})
        if not isinstance(link,dict):return report('BOX_EVIDENCE_INVALID')
        age=link.get('last_box_health_age')
        fresh_health=type(age) in (int,float) and math.isfinite(age) and 0<=age and age+elapsed<45
        instance=body.get('pc_instance');epoch=link.get('origin_epoch')
        complete=(fresh_health and link.get('state')=='READY' and link.get('health_ready') is True and link.get('session_registered') is True
            and type(epoch) is int and 0<epoch<=0xffffffffffffffff and type(instance) is str and re.fullmatch('[0-9a-f]{32}',instance)
            and observed.get('state')=='READY' and observed.get('pc_instance')==instance and observed.get('origin_epoch')==epoch)
        if complete:
            peer_age=udp.get('authenticated_peer_age_s')
            candidate=_neighbor_peer(dict(schema_version=1,ipv4=udp.get('authenticated_peer_ipv4'),subnet=subnet),source,subnet)
            if candidate is None or type(peer_age) not in (int,float) or not math.isfinite(peer_age) or not 0<=peer_age+elapsed<=90:return report('READY_PEER_UNVERIFIED')
            try:
                with lock:
                    if not self._neighbor_permitted(generation):return report('DISABLED')
                    try:old=_neighbor_json(peer_path)
                    except (OSError,ValueError):old=None
                    if old!=candidate:atomic_json(peer_path,candidate,secure=security.secure_file)
                return report('READY_LEARNED')
            except OSError:return report('PEER_SAVE_FAILED')
        expires=observed.get('health_expires_at')
        observed_fresh=type(expires) in (int,float) and math.isfinite(expires) and expires>time.time()
        if fresh_health or observed_fresh or observed.get('state')=='READY':return report('FRESH_BOX_NO_ACTION')
        try:peer=_neighbor_peer(_neighbor_json(peer_path),source,subnet)
        except (OSError,ValueError):peer=None
        if peer is None:return report('NO_TARGET')
        self._stage('box_neighbor_recovery');began=time.monotonic();deadline=began+3;process=None;own_busy=False
        try:
            with lock:
                if not self._neighbor_permitted(generation):return report('DISABLED')
                if self._neighbor_busy:
                    child=self._neighbor_child
                    if child is None or child.poll() is None:return report('BUSY')
                    self._neighbor_child=None;self._neighbor_busy=False
                if _neighbor_peer(_neighbor_json(peer_path),source,subnet)!=peer:return report('TARGET_CHANGED')
                now=time.time();stamps=_neighbor_budget(budget_path,now)
                if len(stamps)>=3 or stamps and now-stamps[-1]<15:return report('RATE_LIMITED')
                atomic_json(budget_path,dict(schema_version=1,attempted_at=stamps+[now]),secure=security.secure_file)
                if not self._neighbor_permitted(generation):return report('DISABLED_RESERVED')
                if time.monotonic()>=deadline:return report('DEADLINE_RESERVED')
                env={key:value for key,value in os.environ.items() if key.upper() in ('SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP')}
                self._neighbor_busy=True;own_busy=True
                process=subprocess.Popen([str(self.python.with_name('python.exe')),'-I','-S','-c',NEIGHBOR_HELPER,
                    peer['ipv4'],source,subnet,str(self.paths.state_dir/'intent.json'),str(generation)],
                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW,env=env,cwd=self.voice_dir)
                self._neighbor_child=process
            try:output,_=process.communicate(timeout=max(.001,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill();process.communicate(timeout=.25)
                return dict(category='TIMEOUT',attempted=True,elapsed_ms=round((time.monotonic()-began)*1000))
            if not self._neighbor_permitted(generation):return dict(category='CANCELLED',attempted=True)
            if process.returncode or len(output)>1024:return dict(category='HELPER_FAILED',attempted=True)
            value=json.loads(output.decode('ascii'))
            if (not isinstance(value,dict) or set(value)!={'schema_version','called','rc','length'} or type(value['schema_version']) is not int or value['schema_version']!=1 or type(value['called']) is not bool
                    or type(value['rc']) is not int or not 0<=value['rc']<=0xffffffff or type(value['length']) is not int or not 0<=value['length']<=8):raise ValueError()
            return dict(category=('ARP_RESOLVED' if value['rc']==0 and value['length']==6 else 'ARP_FAILED') if value['called'] else 'CHILD_STOPPED',
                attempted=True,arp_called=value['called'],arp_rc=value['rc'],length=value['length'],elapsed_ms=round((time.monotonic()-began)*1000))
        except (OSError,ValueError,subprocess.TimeoutExpired):
            return dict(category='RECOVERY_FAILED',attempted=process is not None,cleanup_pending=process is not None and process.poll() is None)
        finally:
            if own_busy:
                if process is not None and process.poll() is None:
                    try:process.kill();process.wait(timeout=.25)
                    except (OSError,subprocess.TimeoutExpired):pass
                with lock:
                    if process is None or process.poll() is not None:self._neighbor_child=None;self._neighbor_busy=False

    def close(self):
        child=getattr(self,'_neighbor_child',None)
        if child is not None and child.poll() is None:
            try:child.kill();child.wait(timeout=.25)
            except (OSError,subprocess.TimeoutExpired):pass
        for entry in self.groups.values():
            if entry.get("handle"):entry["handle"].close()


class FixtureProvider(WindowsProvider):
    """Native fake children only. Cannot query, start or stop production roles."""
    can_manage=True
    def __init__(self,paths,scenario="ready"):
        super().__init__(paths);self.fixture=True;self.scenario=scenario;self.can_manage=True
        self.check_count=0;self.starts={};self.stop_count={};self.fixture_pids=[]
    def begin(self):
        self.check_count+=1
        if not self.ledger_loaded:
            self.records=[]
            try:
                saved=json.loads(self.paths.ledger.read_text(encoding="utf-8"))
                if saved.get("project_root")!=str(self.paths.project.resolve()) or saved.get("user_sid")!=self.paths.sid:
                    return result("UNKNOWN","隔离账本项目或SID不符")
                for entry in saved.get("groups",{}).values():
                    pid=entry.get("pid")
                    if type(pid) is int:
                        try:self.records.extend(peer_record(pid))
                        except (OSError,ValueError,subprocess.TimeoutExpired):pass
                self._load_ledger()
            except FileNotFoundError:pass
            except (OSError,ValueError,AttributeError):return result("UNKNOWN","隔离账本无法解析，保留现场")
            self.ledger_loaded=True
        return None
    def _executable(self,role):return self.python
    def inspect(self,role):
        entry=self.groups.get(role)
        if entry is None:return result("FAILED","隔离假服务不存在",lifecycle="ABSENT")
        handle=entry.get("handle")
        if handle is None:return result("STARTING","隔离子进程尚在启动",lifecycle="STARTING")
        if not handle.alive():return result("FAILED","隔离已创建进程退出",lifecycle="ABSENT",owner="created")
        handle.verify()
        if not entry.get("ledger_saved"):return result("UNKNOWN","隔离账本未保存；保留句柄")
        state="DEGRADED" if role=="voice" and self.scenario=="tts-failed" else "READY"
        probe=time.time()
        evidence=voice_health(dict(status='ok',asr='ready',device_auth='ok',tts=dict(
            configured_primary='edge',active_engine='edge',last_probe_ok=state=='READY',last_probe_ts=probe)),
            'edge',300,now=probe)['tts'] if role=='voice' else None
        return result(state,"TTS最近合成探测失败" if state=="DEGRADED" else "隔离假服务就绪",
                      lifecycle="HEALTHY_CREATED" if state=="READY" else "UNHEALTHY_CREATED",owner="created",
                      pid=entry["pid"],created_at=entry["created_at"],
                      **({'tts':evidence}
                         if role=='voice' else {}))
    def start(self,role):
        self.starts[role]=self.starts.get(role,0)+1
        return super().start(role)
    def stop(self,role):
        self.stop_count[role]=self.stop_count.get(role,0)+1
        return super().stop(role)
    def dependencies(self,voice):
        discovery=('WAIT_NETWORK' if self.scenario=='no-lan' else 'DEGRADED' if self.scenario=='tts-failed' else 'READY')
        return {"discovery":result(discovery,"隔离LAN健康未就绪" if discovery=='DEGRADED' else "隔离LAN观察"),
                "hermes":result("DEGRADED","隔离网关未验证",gateway_healthy=False,access_verified=False),
                "deepseek":result("UNKNOWN","隔离配置存在；实际模型未验",configured=True,request_verified=False),
                "data":result("READY" if voice["state"]=="READY" else "DEGRADED","隔离本地DATA能力",llm_calls=0),
                "memory":result("READY","隔离鉴权通过"),"memory_read":result("READY","隔离本地文件可读")}
