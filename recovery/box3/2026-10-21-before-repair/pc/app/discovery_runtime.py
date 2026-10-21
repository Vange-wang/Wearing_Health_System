"""Voice-lifespan ownership and authenticated BOX-only background receipts."""
from pathlib import Path
import ipaddress,json,re,secrets,threading,time
from .discovery_protocol import DiscoveryKey,ProtocolError
from .discovery_udp import DiscoveryResponder,DiscoveryService

class PhysicalInterface:
    def __init__(self,project,clock=time.monotonic):
        self.project=project;self.clock=clock;self.at=float('-inf');self.cached=None
    def __call__(self):
        now=self.clock()
        if now-self.at>=5:
            self.at=now;self.cached=None
            from service_control.native_adapters import adapters
            from service_control.checks import choose_lan
            try:
                chosen=json.loads((self.project/'voice-bridge/logs/service-control/settings.json').read_text(encoding='utf-8')).get('interface_index')
                if type(chosen) is not int:chosen=None
            except (OSError,ValueError,AttributeError):chosen=None
            rows=adapters();result=choose_lan(rows,chosen)
            if result['state']=='READY':
                row=result['selected']
                raw=next((item for item in rows if item.get('index')==row['index'] and item.get('address')==row['address']),{})
                prefix=raw.get('prefix_length')
                if type(prefix) is int and 1<=prefix<=30:
                    self.cached=(row['address'],str(ipaddress.IPv4Network((row['address'],prefix),strict=False).netmask))
        if self.cached is None:raise ValueError('selected_physical_interface_unavailable')
        return self.cached

class BoxReceipts:
    def __init__(self,auth,instance,clock=time.monotonic):
        self.auth=auth;self.instance=instance.hex();self.clock=clock;self.lock=threading.Lock()
        self.epoch=0;self.health_at=None;self.session_at=None;self.ready=False
        self.store=None;self.session_version=None
    def context(self,request):
        headers=request.headers
        if headers.getlist('x-voice-client')!=['box3']:return None
        token=headers.getlist('x-device-token');instance=headers.getlist('x-voice-pc-instance');epoch=headers.getlist('x-voice-origin-epoch')
        try:
            if (len(token)!=1 or not self.auth.token or not secrets.compare_digest(token[0],self.auth.token)
                    or instance!=[self.instance] or len(epoch)!=1 or not re.fullmatch(r'[1-9][0-9]{0,19}',epoch[0])
                    or int(epoch[0])>0xffffffffffffffff):return None
        except TypeError:return None
        return int(epoch[0])
    def health(self,request,ready):
        epoch=self.context(request)
        if epoch is None:return
        with self.lock:
            if self.session_at is not None and epoch!=self.epoch:return
            if epoch!=self.epoch:
                self.epoch=epoch;self.session_at=None;self.store=None
            self.health_at=self.clock();self.ready=ready is True
    def session_allowed(self,request):
        if request.headers.getlist('x-voice-client')!=['box3']:return True
        epoch=self.context(request)
        return epoch is not None  # fresh existing session challenge fences BOX reboots, not numeric epoch ordering
    def session(self,request,store):
        epoch=self.context(request)
        if epoch is None:return
        with self.lock:
            if epoch!=self.epoch:self.epoch=epoch;self.health_at=None;self.ready=False
            self.session_at=self.clock();self.store=store;self.session_version=len(store.sessions_seen)
    def status(self):
        with self.lock:
            now=self.clock();health_age=None if self.health_at is None else max(0,now-self.health_at)
            session_age=None if self.session_at is None else max(0,now-self.session_at)
            registered=self.store is not None and self.store.session is not None and len(self.store.sessions_seen)==self.session_version
            fresh=health_age is not None and health_age<45
            ready=fresh and self.ready and registered and self.session_at is not None
            state='READY' if ready else ('UNKNOWN' if not fresh else 'DEGRADED')
            return dict(state=state,origin_epoch=self.epoch,last_box_health_age=health_age,last_box_session_age=session_age,
                        health_ready=self.ready if fresh else False,session_registered=bool(registered))

class DiscoveryRuntime:
    def __init__(self,auth,*,interface=None,instance=None,clock=time.monotonic,service_factory=DiscoveryService):
        self.instance=instance if instance is not None else secrets.token_bytes(16)
        self.receipts=BoxReceipts(auth,self.instance,clock);self.service=None;self.key=None;self.error=None
        try:self.key=DiscoveryKey(auth.token)
        except ProtocolError:self.error='UNSUPPORTED_TOKEN'
        if self.key is not None:
            try:
                interface=interface or PhysicalInterface(Path(__file__).resolve().parents[2],clock)
                self.service=service_factory(DiscoveryResponder(self.key,interface,instance=self.instance,clock=clock))
            except Exception:
                self.error='INITIALIZATION_FAILED';self.key.close()
    def start(self):
        if self.service:
            try:self.service.start()
            except Exception:
                self.error='START_FAILED'
                raise
    def close(self):
        try:
            if self.service:self.service.close()
        finally:
            if self.key:self.key.close()
    def status(self):
        return dict(pc_instance=self.instance.hex(),discovery_udp=self.service.status() if self.service and not self.error else dict(listener=self.error),
                    box_link=self.receipts.status())

def runtime(request):return getattr(request.app.state,'discovery_runtime',None)
