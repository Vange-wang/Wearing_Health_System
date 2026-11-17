"""One lifespan-owned UDP listener; bounded work independent of audio/HTTP."""
import ipaddress,secrets,socket,threading,time
from .discovery_protocol import DiscoveryKey,ProtocolError,request_shape,ordinary_peer,UDP_PORT

class Bucket:
    def __init__(self,rate,burst,now):self.rate=rate;self.burst=burst;self.tokens=float(burst);self.at=now
    def take(self,now):
        self.tokens=min(self.burst,self.tokens+max(0,now-self.at)*self.rate);self.at=now
        if self.tokens<1:return False
        self.tokens-=1;return True

def routed_local_ip(remote):
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as probe:
        probe.connect((remote,UDP_PORT))  # routing query only; send is never called
        return probe.getsockname()[0]

class DiscoveryResponder:
    def __init__(self,key,interface,*,instance=None,route=routed_local_ip,clock=time.monotonic):
        self.key=key;self.interface=interface;self.route=route;self.clock=clock
        self.instance=instance if instance is not None else secrets.token_bytes(16)
        if len(self.instance)!=16:raise ValueError('invalid_instance')
        self.candidates=Bucket(32,32,clock());self.responses=Bucket(8,4,clock());self.sources={}
        self.last_authenticated=None;self.network_state='WAIT_NETWORK'
        self.verified_peer=None
        self.interface_snapshot=(None,None,'UNQUERIED');self.next_interface_refresh=float('-inf')
        self.counters=dict.fromkeys(('rx','shape_ok','shape_reject','candidate_limit_drop','mac_ok','mac_reject',
            'route_ok','route_reject','interface_error','source_table_drop','source_limit_drop','response_limit_drop',
            'reply','send_ok','send_error','recv_error','recv_oversize'),0)
    def count(self,name):self.counters[name]=min(0xffffffff,self.counters[name]+1)
    def _remember_interface(self,address,mask,at):
        selected=None
        try:
            network=ipaddress.IPv4Network((address,mask),strict=False)
            if 1<=network.prefixlen<=30:selected=dict(address=str(ipaddress.IPv4Address(address)),network=str(network))
        except (ValueError,TypeError):pass
        self.interface_snapshot=(selected,at,'READY' if selected else 'UNAVAILABLE')
    def refresh_interface(self):
        """Only the existing UDP owner calls this; never a status/ASGI reader."""
        now=self.clock()
        if now<self.next_interface_refresh:return
        self.next_interface_refresh=now+5
        try:address,mask=self.interface()
        except (OSError,ValueError,TypeError):self.interface_snapshot=(None,now,'UNAVAILABLE');return
        self._remember_interface(address,mask,now)
    def reply(self,packet,source):
        self.count('rx')
        now=self.clock()
        if not request_shape(packet):self.count('shape_reject');return None
        self.count('shape_ok')
        if not self.candidates.take(now):self.count('candidate_limit_drop');return None
        try:nonce=self.key.verify_request(packet)
        except ProtocolError:self.count('mac_reject');return None
        self.count('mac_ok')
        try:
            address,mask=self.interface()
            if not 1<=source[1]<=65535 or not ordinary_peer(source[0],address,mask) or self.route(source[0])!=address:
                self.count('route_reject');self.network_state='WAIT_NETWORK';return None
        except (OSError,ValueError,TypeError):
            self.count('interface_error');self.count('route_reject');self.network_state='WAIT_NETWORK';return None
        self.count('route_ok')
        self._remember_interface(address,mask,now)
        self.verified_peer=(str(ipaddress.IPv4Address(source[0])),now)
        self.network_state='READY'
        entry=self.sources.get(source[0])
        if entry is None:
            self.sources={ip:item for ip,item in self.sources.items() if now-item[1]<60}
            if len(self.sources)>=32:self.count('source_table_drop');return None
            entry=(Bucket(1,2,now),now)
        self.sources[source[0]]=(entry[0],now)
        if not entry[0].take(now):self.count('source_limit_drop');return None
        if not self.responses.take(now):self.count('response_limit_drop');return None
        self.last_authenticated=now
        self.count('reply')
        return self.key.response(nonce,address,self.instance)
    def status(self):
        stamp=self.last_authenticated
        selected,at,state=self.interface_snapshot
        age=None if at is None else max(0,self.clock()-at)
        if state=='READY' and age>=10:selected=None;state='STALE'
        peer=self.verified_peer
        return dict(network_state=self.network_state,pc_instance=self.instance.hex(),
                    last_authenticated_discovery_age=None if stamp is None else max(0,self.clock()-stamp),
                    authenticated_peer_ipv4=peer[0] if peer else None,
                    authenticated_peer_age_s=max(0,self.clock()-peer[1]) if peer else None,selected_subnet=selected.copy() if selected else None,
                    selected_subnet_state=state,selected_subnet_age_s=age,
                    counters=self.counters.copy())

class DiscoveryService:
    def __init__(self,responder,*,socket_factory=socket.socket):
        self.responder=responder;self.factory=socket_factory;self.socket=None;self.thread=None
        self.stop_event=threading.Event();self.lifecycle_lock=threading.Lock();self.state='STOPPED'
    def poll_once(self):
        for _ in range(4):
            try:packet,source=self.socket.recvfrom(83)
            except BlockingIOError:break
            except OSError as error:
                self.responder.count('recv_error')
                if getattr(error,'winerror',None)==10040:self.responder.count('recv_oversize')
                if getattr(error,'winerror',None) in (10040,10054,10052):continue  # oversized/ICMP datagram, retain listener
                raise
            response=self.responder.reply(packet,source)
            if response is not None:
                try:
                    sent=self.socket.sendto(response,source)
                    self.responder.count('send_ok' if sent==len(response) else 'send_error')
                except OSError:self.responder.count('send_error')  # not listener death or BOX proof
    def start(self):
        with self.lifecycle_lock:
            if self.thread is not None:return
            try:sock=self.factory(socket.AF_INET,socket.SOCK_DGRAM)
            except OSError:self.state='SOCKET_CREATE_FAILED';return
            try:
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                sock.bind(('0.0.0.0',UDP_PORT));sock.setblocking(False)
            except OSError:
                self.state='BIND_FAILED'
                sock.close();return
            self.socket=sock;self.stop_event.clear();self.state='LISTENING'
            try:
                self.thread=threading.Thread(target=self._run,name='paired-discovery',daemon=True);self.thread.start()
            except RuntimeError:
                self.socket=None;self.thread=None;self.state='THREAD_FAILED';sock.close()
    def _run(self):
        try:
            while not self.stop_event.wait(.1):
                self.responder.refresh_interface()
                self.poll_once()
        except OSError:self.state='SOCKET_FAILED'
        finally:
            self.socket.close();self.socket=None
    def close(self):
        with self.lifecycle_lock:
            self.stop_event.set()
            if self.thread is not None:
                self.thread.join(1)
                if self.thread.is_alive():self.state='STOP_PENDING';return
            self.thread=None;self.state='STOPPED'
    def status(self):return dict(listener=self.state,**self.responder.status())
