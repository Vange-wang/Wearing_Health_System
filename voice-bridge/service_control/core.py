"""Single mutation worker; 2s publication is independent of 60s checks."""
from collections import OrderedDict
import copy
import logging
import os
import threading
import time
import uuid
import json
from .intent import IntentStore
from .checks import overall, result
from .ipc import PipeServer
from .state import atomic_json
from .windows import Security, Mutex, process_created

log = logging.getLogger("voice-control")


class ControlCore:
    def __init__(self, paths, provider, *, clock=time.monotonic, wall=time.time):
        self.paths, self.provider = paths, provider
        self.clock, self.wall = clock, wall
        self.lock = threading.RLock()
        self.launch_lock=threading.RLock()
        self.intent=IntentStore(paths,fixture=getattr(provider,'fixture',True))
        self.intent_generation=self.intent.value['intent_generation']
        self.start_barrier=self.intent.value['start_generation'] if self.intent.value['enabled'] else self.intent_generation+1
        self.wake = threading.Event()
        self.exit = threading.Event()
        self.enabled = self.intent.value['enabled']
        self.stop_requested = self.intent.valid and not self.enabled
        self.pending = self.enabled or self.stop_requested
        self.shutdown_requested = False
        self.requests = OrderedDict()
        for op in self.intent.value['operations']:self.requests[op['id']]=op['command']
        self.stop_previews = OrderedDict()
        self.stop_targets = None
        self.failure_count = {}
        self.recoveries = {}
        self.provider.recovery_history=self.recoveries
        # Bounded accounting only, never process ownership or stop authority.
        self.managed_roles=set(getattr(provider,'managed_roles',())) & {'voice','mdns','memory_service'}
        self.provider.managed_roles=self.managed_roles
        self.round_started = self.clock()
        self.request_seq=max((op['sequence'] for op in self.intent.value['operations']),default=0);self.completed_seq=0;self.error_seq=0
        self.manual_attempts=set();self.manual_recovery_generation=None
        self.active_operation=None
        self.progress_stamp=self.clock();self.phase_deadline=self.clock()+30
        self.current_stage='initialization'
        self.provider.launch_lock=self.launch_lock
        self.provider.start_permitted=lambda generation=None:self.enabled and (generation is None or generation>=self.start_barrier)
        self.provider.intent_generation=lambda:self.intent_generation
        self.provider.report_stage=self.phase
        self.identity = dict(core_instance_id=uuid.uuid4().hex, core_pid=os.getpid(),
                             core_created_at=process_created(os.getpid()))
        self.state = dict(schema_version=1,snapshot_seq=0,project_root=str(paths.project.resolve()),
                          user_sid=paths.sid,updated_at=0,overall="CHECKING",components={},
                          reason="正在检查语音服务",phase="前置检查",round_elapsed_s=0,
                          **self.identity)
        self.provider.owner = self.identity["core_instance_id"]
        if not self.enabled:self.state.update(overall='UNKNOWN',reason=self.intent.error or '停止意图已保存，待核旧账本',phase='待机/停止核验')

    def dispatch(self, request):
        identifier, command = request["request_id"], request["command"]
        with self.lock:
            if command=="status":
                preview=copy.deepcopy(self.provider.created_summary())
                self.stop_previews[identifier]=(self.clock(),preview)
                while len(self.stop_previews)>256:self.stop_previews.popitem(last=False)
                return dict(schema_version=1,request_id=identifier,accepted=True,identity=dict(self.identity),
                            snapshot=copy.deepcopy(self.state),stop_preview_id=identifier,stop_candidates=preview)
            previous = self.requests.get(identifier)
            if previous is not None:
                if previous != command:
                    return dict(schema_version=1,request_id=identifier,accepted=False,reason="request_id已用于其他命令")
            elif command != "status":
                security=getattr(self.provider,'security',None)
                secure=security.secure_file if security else None
                active=self.active_operation
                if command in ('ensure','retry') and self.enabled and not self.stop_requested and active is not None:
                    try:
                        self.intent_io_deadline=self.clock()+10
                        self.intent.alias(dict(id=identifier,command=command,sequence=active['sequence'],state='queued'),active,secure=secure)
                    except (OSError,ValueError):
                        return dict(schema_version=1,request_id=identifier,accepted=False,reason='合并回执未持久化')
                    finally:self.intent_io_deadline=float('inf')
                    self.requests=OrderedDict((op['id'],op['command']) for op in self.intent.value['operations'])
                    return dict(schema_version=1,request_id=identifier,accepted=True,coalesced=True,
                                operation=dict(active),identity=dict(self.identity),snapshot=copy.deepcopy(self.state))
                if command in ('ensure','retry') and self.enabled and self.wall()<self.intent.value.get('manual_not_before',0):
                    return dict(schema_version=1,request_id=identifier,accepted=False,reason='手动尝试冷却中',
                                retry_after_s=round(self.intent.value['manual_not_before']-self.wall(),1))
                if command=='stop':
                    preview=self.stop_previews.get(identifier)
                    if preview is None or self.clock()-preview[0]>120:
                        return dict(schema_version=1,request_id=identifier,accepted=False,reason='停止确认已过期，请重新核对具体对象')
                if command in ('ensure','stop','retry'):
                    if command=='retry' and not self.enabled:
                        return dict(schema_version=1,request_id=identifier,accepted=False,reason='已停止，请从启动入口重新启用')
                    try:
                        with self.launch_lock:
                            security=getattr(self.provider,'security',None)
                            self.intent_io_deadline=self.clock()+10
                            value=self.intent.commit(command!='stop',secure=security.secure_file if security else None,
                                operation=dict(id=identifier,command=command,sequence=self.request_seq+1,state='queued'),
                                manual_not_before=self.wall()+5 if command in ('ensure','retry') else None)
                            self.intent_io_deadline=float('inf')
                            self.intent_generation=value['intent_generation']
                            self.enabled=value['enabled']
                            if command=='stop':self.start_barrier=self.intent_generation+1
                    except (OSError,ValueError):
                        self.intent_io_deadline=float('inf')
                        return dict(schema_version=1,request_id=identifier,accepted=False,reason='停止/启动意图未持久化，未受理')
                if command == "stop":
                    preview=self.stop_previews.get(identifier)
                    if preview is None or self.clock()-preview[0]>120:
                        return dict(schema_version=1,request_id=identifier,accepted=False,reason="停止确认已过期，请重新核对具体对象")
                    self.stop_targets={(e["name"],e["pid"],e.get("created_at")) for e in preview[1] if e.get("verified") is True}
                    self.enabled = False
                    self.stop_requested = True
                    self.state.update(overall="CHECKING",reason="停止请求已排队；自动恢复已关闭",phase="等待安全停止")
                elif command == "ensure":
                    self.stop_requested=False;self.stop_targets=None
                    was_enabled=self.enabled
                    self.enabled = True
                    if not was_enabled or self.state["overall"] not in ("CHECKING","STARTING"):
                        self.round_started = self.clock()
                elif not self.enabled:
                    return dict(schema_version=1,request_id=identifier,accepted=False,reason="已停止，请从启动入口重新启用")
                elif command == "retry":
                    self.round_started=self.clock()
                self.requests[identifier] = command
                while len(self.requests)>256:self.requests.popitem(last=False)
                self.pending = True
                self.request_seq+=1
                if command in ('ensure','retry'):
                    self.manual_attempts={'voice','mdns','memory_service'}
                    self.active_operation=dict(id=identifier,command=command,sequence=self.request_seq,state='queued')
                else:self.active_operation=None;self.manual_attempts.clear()
                self.state.update(overall='CHECKING',operation=dict(request_id=identifier,sequence=self.request_seq,state='queued'))
                self.wake.set()
            receipt=next((dict(op) for op in self.intent.value['operations'] if op['id']==identifier),None)
            if receipt is not None and self.active_operation is not None and receipt['sequence']==self.active_operation['sequence']:
                receipt=dict(self.active_operation)
            return dict(schema_version=1,request_id=identifier,accepted=True,
                        operation=receipt,
                        identity=dict(self.identity),snapshot=copy.deepcopy(self.state))

    def set_component(self, name, value):
        value = dict(value,last_check_at=self.wall())
        with self.lock:self.state["components"][name] = value

    def phase(self, text):
        self.current_stage=text;self.progress_stamp=self.clock();self.phase_deadline=self.clock()+30
        with self.lock:self.state["phase"] = text

    def recovery_allowed(self, name):
        now = self.clock()
        values = [stamp for stamp in self.recoveries.get(name,[]) if now-stamp<300]
        self.recoveries[name] = values
        return len(values)<2 and (not values or now-values[-1]>=30)

    def check(self):
        self.phase("核对旧守护及进程身份")
        gate = self.provider.begin()
        if gate is not None:
            self.set_component("voice",gate)
            with self.lock:self.state.update(overall=gate["state"],reason=gate["reason"])
            return
        components = {}
        for name in ("voice", "mdns", "memory_service"):
            self.phase("检查 " + name)
            try:value=self.check_component(name)
            except Exception as error:
                value=result("FAILED",name+" 启动/检查失败："+type(error).__name__)
            self.set_component(name,value);components[name]=value
            with self.lock:self.state["created"]=self.provider.created_summary()
        self.phase("检查LAN、工具与记忆能力")
        dependencies = self.provider.dependencies(components["voice"])
        for name,value in dependencies.items():self.set_component(name,value)
        for role,dependency in (('mdns','discovery'),('memory_service','memory')):
            process=components[role];checked=dependencies.get(dependency)
            if process['state']=='CHECKING' and checked is not None:
                state=checked['state'];owner=process.get('owner','unknown')
                self.set_component(role,dict(process,state=state,reason=checked['reason'],
                    lifecycle=('HEALTHY_' if state=='READY' else 'UNHEALTHY_')+owner.upper()))
        with self.lock:
            self.state["created"] = self.provider.created_summary()
            self.state["overall"] = overall(self.state["components"]) if self.enabled else "STOPPED"
            self.state["reason"] = "依赖检查完成；外部模型、微信/搜索工具和设备回答另验"
            self.state["phase"] = "监控中" if self.enabled else "已停止自动恢复"
            if getattr(self.provider,"fixture",False):
                self.state["fixture_stats"]=dict(checks=self.provider.check_count,starts=dict(self.provider.starts),stops=dict(self.provider.stop_count))

    def check_component(self,name):
        value = self.provider.inspect(name)
        with self.lock:enabled = self.enabled and not self.stop_requested
        created = self.provider.created(name)
        local_fault=value.get('fault_kind') in ('local_no_listener','local_no_http')
        # Compatibility for the explicitly documented old local-startup reason.
        local_fault=local_fault or (value.get('reason')=='创建进程在运行，监听归属尚未确认')
        started=value.get('startup_at')
        deadline=started+120 if isinstance(started,(int,float)) else self.round_started+120
        timed_out=created and local_fault and self.clock()>=deadline
        if timed_out:
            self.failure_count[name]=self.failure_count.get(name,0)+1
            if self.failure_count[name]>=2:value=dict(value,lifecycle='ABSENT',fault_kind='local_startup_timeout')
        if value.get("lifecycle") == "ABSENT" and enabled:
            manual=name in self.manual_attempts
            if manual:self.manual_attempts.discard(name)
            has_history = bool(self.recoveries.get(name))
            if created or has_history or name in self.managed_roles:
                if not timed_out:self.failure_count[name] = self.failure_count.get(name,0)+1
                if not manual and not self.recovery_allowed(name):
                    stamps=self.recoveries.get(name,[]);now=self.clock()
                    delay=max([0]+([stamps[-1]+30-now] if stamps else [])+([stamps[0]+300-now] if len(stamps)>=2 else []))
                    value = result("FAILED","自动恢复达到冷却/次数限制",lifecycle="UNHEALTHY_CREATED",retry_after_s=round(delay,1))
                elif not created or self.failure_count[name]>=2:
                    # Reserve/persist before stop/start; dead groups can lose
                    # their created handle across a core restart or failed start.
                    if not manual:self.recoveries.setdefault(name,[]).append(self.clock())
                    persist=getattr(self.provider,'persist_recovery',None)
                    if persist is not None:persist()
                    if created:self.provider.stop(name)
                    value = self.provider.start(name)
                    if not manual and value.get('spawn_attempted') is False and value.get('fault_kind','').startswith('dependency_'):
                        # The reserved restart never reached Popen. Refund only
                        # this verified preflight outcome; crashes stay charged.
                        self.recoveries[name].pop()
                        if persist is not None:persist()
            else:
                # Persist entry into managed life before the first launch. A
                # failed launch or core restart must not become "first" again.
                self.managed_roles.add(name)
                persist=getattr(self.provider,'persist_recovery',None)
                if persist is not None:persist()
                value = self.provider.start(name)
        elif value.get("lifecycle") != "ABSENT" and not timed_out:
            self.failure_count[name] = 0
        if value["state"]=="STARTING" and self.clock()>=deadline:
            value = dict(value,state="FAILED",reason="启动未就绪（120秒）")
        return value

    def stop_created(self):
        self.phase("停止已核验的本管理器服务")
        if not getattr(self.provider,'ledger_loaded',True):
            gate=self.provider.begin()
            if gate is not None:
                with self.lock:self.state.update(overall='UNKNOWN',reason='停止意图已保存，旧账本尚未核验')
                return
        for name in ("voice","mdns","memory_service"):
            if self.provider.created(name):
                if self.stop_targets is not None:
                    current=next((e for e in self.provider.created_summary() if e["name"]==name),None)
                    if current is None or (name,current["pid"],current.get("created_at")) not in self.stop_targets:continue
                try:
                    self.provider.stop(name)
                    if not self.provider.created(name):
                        self.set_component(name,result("STOPPED","本管理器已核验进程已停止",lifecycle="ABSENT",owner="absent"))
                except (OSError,ValueError,TimeoutError):
                    self.set_component(name,result("UNKNOWN","停止归属未确认，保留进程"))
        with self.lock:
            remaining=bool(self.provider.created_summary()) or bool(getattr(self.provider,'unresolved_roles',set()))
            self.stop_requested = remaining
            self.stop_targets=None
            self.state.update(overall='UNKNOWN' if remaining else 'STOPPED',reason='停止意图已保存，仍有对象待核验/停止' if remaining else '自动恢复已关闭；复用及共享对象保留',phase='停止核验中' if remaining else '已停止自动恢复')
            if self.enabled:
                self.pending=True;self.state.update(overall='CHECKING',reason='新的显式启动意图已排队')
            self.state["created"] = self.provider.created_summary()

    def worker(self):
        due = self.clock()
        while not self.exit.is_set():
            with self.lock:
                stop = self.stop_requested
                run = self.pending or self.enabled and self.clock()>=due
                self.pending = False
                sequence=self.request_seq
            try:
                if stop:
                    self.stop_created()
                    if not self.stop_requested:
                        security=getattr(self.provider,'security',None)
                        with self.lock:
                            self.intent.finish(sequence,secure=security.secure_file if security else None)
                            if sequence==self.request_seq and 'operation' in self.state:self.state['operation']['state']='completed'
                    if self.shutdown_requested:return
                elif run:
                    self.phase('checking');self.check()
                    with self.lock:
                        if sequence==self.request_seq:
                            security=getattr(self.provider,'security',None)
                            self.intent.finish(sequence,secure=security.secure_file if security else None)
                            self.completed_seq=sequence
                            self.active_operation=None;self.manual_attempts.clear()
                            if 'operation' in self.state:self.state['operation']['state']='completed'
                        else:self.state['overall']='CHECKING'
            except Exception as error:
                self.error_seq+=1
                detail=dict(core_instance_id=self.identity['core_instance_id'],operation_seq=sequence,
                            error_seq=self.error_seq,stage=self.current_stage,error_category=type(error).__name__,at=self.wall())
                log.error(json.dumps(detail,ensure_ascii=False),extra={'stage':self.current_stage,'error_seq':self.error_seq})
                with self.lock:self.state.update(overall="FAILED",reason="检查失败："+type(error).__name__,phase="检查未完成")
            if run:
                starting=any(v.get('state')=='STARTING' or v.get('fault_kind') in ('local_no_listener','local_no_http') for v in self.state['components'].values())
                due=self.clock()+(2 if starting or self.stop_requested else 60)
            with self.lock:enabled=self.enabled or self.stop_requested
            self.current_stage='idle';self.phase_deadline=float('inf');self.progress_stamp=self.clock()
            self.wake.wait(max(0.1,due-self.clock()) if enabled else None)
            self.wake.clear()

    def publish(self, security):
        with self.lock:
            snapshot = copy.deepcopy(self.state)
            snapshot["snapshot_seq"] += 1
            snapshot["updated_at"] = self.wall()
            snapshot["round_elapsed_s"] = round(self.clock()-self.round_started,1)
        try:atomic_json(self.paths.snapshot,snapshot,secure=security.secure_file)
        except OSError:
            log.error("snapshot replace failed; prior valid snapshot retained")
            return False
        with self.lock:
            self.state["snapshot_seq"] = snapshot["snapshot_seq"]
            self.state["updated_at"] = snapshot["updated_at"]
            self.state["round_elapsed_s"] = snapshot["round_elapsed_s"]
        return True

    def watchdog(self, worker, security, *, fatal=os._exit):
        # Dedicated watchdog never waits on self.lock or the launch lock.
        while not self.exit.wait(1):
            now=self.clock()
            stalled=now>self.phase_deadline+5 or now>getattr(self,'intent_io_deadline',float('inf')) or (self.enabled and self.current_stage=='idle' and now-self.progress_stamp>95)
            if not worker.is_alive() or stalled:
                error=dict(core_instance_id=self.identity['core_instance_id'],stage=self.current_stage,
                           error_category='worker_dead' if not worker.is_alive() else 'phase_deadline',
                           error_seq=self.error_seq+1,at=self.wall())
                try:atomic_json(self.paths.state_dir/'watchdog-error.json',error,secure=security.secure_file)
                finally:fatal(70)
                return

    def run(self, *, fixture_lifetime=None):
        security = Security(self.paths.sid)
        mutex = Mutex(self.paths.mutex,security)
        if mutex.existing:
            mutex.close();security.close();return 0
        self.paths.state_dir.mkdir(parents=True,exist_ok=True)
        security.secure_file(self.paths.state_dir)
        self.provider.security = security
        if self.intent.valid:
            self.request_seq+=1
            boot=dict(id='boot-'+self.identity['core_instance_id'],command='startup',sequence=self.request_seq,state='queued')
            try:
                request=json.loads((self.paths.state_dir/'task-request.json').read_text(encoding='utf-8'))
                if (isinstance(request.get('id'),str) and len(request['id'])==32 and all(c in '0123456789abcdef' for c in request['id'])
                    and type(request.get('requested_at')) in (int,float) and 0<=self.wall()-request['requested_at']<=30):boot['id']=request['id']
            except (OSError,ValueError,TypeError):pass
            value=self.intent.commit(self.enabled,secure=security.secure_file,operation=boot)
            self.intent_generation=value['intent_generation']
            self.state['operation']=dict(request_id=boot['id'],sequence=self.request_seq,state='queued')
        worker = threading.Thread(target=self.worker,name="control-worker",daemon=True)
        server = PipeServer(self.paths,self.dispatch)
        try:
            self.publish(security);server.start();worker.start()
            monitor=threading.Thread(target=self.watchdog,args=(worker,security),name='core-watchdog',daemon=True)
            monitor.start()
            started = self.clock()
            while not self.exit.wait(2):
                if fixture_lifetime is None or not (self.paths.state_dir/"fixture-pause-publication").exists():
                    self.publish(security)
                if fixture_lifetime is not None and self.clock()-started>=fixture_lifetime:break
        finally:
            if fixture_lifetime is not None:
                with self.lock:
                    self.enabled=False;self.stop_requested=True;self.shutdown_requested=True
                    self.stop_targets=None
                self.wake.set();worker.join(45)
            # Production abnormal exits preserve the verified ledger/children.
            # Task Scheduler restarts the core, which must reverify them.
            self.exit.set();self.wake.set()
            server.close();self.provider.close();mutex.close();security.close()
        return 0
