"""Application-only, TTL-bound DNS cache for the geocoding hostname.

Public DNS runs in a startup/background worker, never on a voice request.
HTTP keeps the original URL/Host/TLS SNI and certificate verification. There
is no process-wide getaddrinfo patch and no pinned weather-server address.
"""
import ipaddress,secrets,socket,struct,threading,time
import httpcore
from .http_stream_transport import cancellable_transport

HOST='geocoding-api.open-meteo.com'
SERVERS=('8.8.8.8','1.1.1.1')

def name_at(data,offset):
    labels=[];end=None;seen=set()
    for _ in range(128):
        if offset>=len(data) or offset in seen:raise ValueError('invalid DNS name')
        seen.add(offset);n=data[offset];offset+=1
        if n==0:return '.'.join(labels).lower(),offset if end is None else end
        if n&192==192:
            if offset>=len(data):raise ValueError('truncated DNS pointer')
            pointer=((n&63)<<8)|data[offset]
            if end is None:end=offset+1
            offset=pointer;continue
        if n&192 or n>63 or offset+n>len(data):raise ValueError('invalid DNS label')
        labels.append(data[offset:offset+n].decode('ascii'));offset+=n
        if sum(map(len,labels))+len(labels)>254:raise ValueError('DNS name too long')
    raise ValueError('DNS name loop')

def parse_answer(data,transaction,host=HOST):
    if len(data)<12:raise ValueError('short DNS packet')
    ident,flags,questions,answers,_,_=struct.unpack_from('!6H',data)
    if ident!=transaction or flags&0xF80F!=0x8000 or flags&0x0200 or questions!=1 or answers>64:
        raise ValueError('DNS response rejected')
    question,at=name_at(data,12)
    if question!=host or at+4>len(data) or data[at:at+4]!=b'\0\1\0\1':raise ValueError('DNS question mismatch')
    at+=4;records=[]
    for _ in range(answers):
        owner,at=name_at(data,at)
        if at+10>len(data):raise ValueError('short DNS record')
        kind,cls,ttl,size=struct.unpack_from('!HHIH',data,at);at+=10;end=at+size
        if end>len(data):raise ValueError('short DNS data')
        value=None
        if cls==1 and kind==1 and size==4:value=str(ipaddress.IPv4Address(data[at:end]))
        if cls==1 and kind==5:
            value,consumed=name_at(data,at)
            if consumed!=end:raise ValueError('invalid CNAME size')
        if value is not None:records.append((owner,kind,ttl,value))
        at=end
    target=host;ttl=3600;visited=set()
    for _ in range(16):
        if target in visited:raise ValueError('CNAME cycle')
        visited.add(target)
        ips=[]
        for owner,kind,age,value in records:
            if owner==target and kind==1:
                address=ipaddress.ip_address(value)
                if not address.is_global or address.is_multicast:raise ValueError('non-public DNS address')
                ips.append(value);ttl=min(ttl,age)
        if ips:
            if ttl<1:raise ValueError('expired DNS answer')
            return tuple(dict.fromkeys(ips))[:4],ttl
        aliases=[(age,value) for owner,kind,age,value in records if owner==target and kind==5]
        if len(aliases)!=1:raise ValueError('missing or ambiguous DNS answer')
        age,target=aliases[0];ttl=min(ttl,age)
    raise ValueError('CNAME chain too long')

def public_query(server):
    transaction=secrets.randbelow(65536)
    name=b''.join(bytes([len(x)])+x.encode('ascii') for x in HOST.split('.'))+b'\0'
    query=struct.pack('!6H',transaction,0x0100,1,0,0,0)+name+b'\0\1\0\1'
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.settimeout(1.2);sock.connect((server,53));sock.send(query)
        response=sock.recv(4096)
    return parse_answer(response,transaction)

class WeatherDNS:
    def __init__(self,clock=time.monotonic,query=public_query):
        self.clock,self.query=clock,query;self.lock=threading.Lock()
        self.addresses=();self.expires=0;self.thread=None;self.stop=threading.Event()
    def refresh(self):
        for server in SERVERS:
            try:addresses,ttl=self.query(server)
            except (OSError,ValueError,UnicodeError):continue
            with self.lock:self.addresses=addresses;self.expires=self.clock()+min(ttl,3600)
            return min(ttl/2,60)
        return 5
    def cached(self,host):
        if host!=HOST:return None
        with self.lock:
            if self.clock()>=self.expires or not self.addresses:raise OSError('weather DNS not ready')
            return self.addresses
    def _run(self):
        while not self.stop.is_set():
            wait=self.refresh()
            if self.stop.wait(max(.5,wait)):break
    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():return
            self.stop.clear();self.thread=threading.Thread(target=self._run,name='weather-dns-refresh',daemon=True)
            self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread is not None:self.thread.join(3)

cache=WeatherDNS()
class CachedBackend:
    def __init__(self,backend,resolver=cache):self.backend,self.resolver=backend,resolver
    def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        try:addresses=self.resolver.cached(host)
        except OSError as exc:raise httpcore.ConnectError(str(exc)) from None
        if addresses is None:
            return self.backend.connect_tcp(host,port,timeout,local_address,socket_options)
        # Resolution is already cached. This changes the TCP destination only;
        # httpcore still invokes start_tls with the original request hostname.
        return self.backend.connect_tcp(addresses[0],port,timeout,local_address,socket_options)
    def connect_unix_socket(self,*args,**kwargs):return self.backend.connect_unix_socket(*args,**kwargs)
    def sleep(self,*args,**kwargs):return self.backend.sleep(*args,**kwargs)

def weather_transport():
    transport=cancellable_transport()
    transport._pool._network_backend=CachedBackend(transport._pool._network_backend)
    return transport
