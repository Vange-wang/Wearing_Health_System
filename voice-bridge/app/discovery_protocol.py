"""Paired BOX discovery v1. Fixed binary frames; no network/credential IO."""
from dataclasses import dataclass
import hashlib,hmac,ipaddress,struct

MAGIC=b'VBXD0001'
VERSION=1
UDP_PORT=8711
HTTP_PORT=8710
REQUEST_BYTES=58
RESPONSE_BYTES=82
SALT=b'voicebridge/box-discovery/hkdf-sha256/v1'
INFO=b'voicebridge/box-discovery/hmac-key/v1'

class ProtocolError(ValueError):pass

@dataclass(frozen=True)
class Response:
    address:str
    instance:bytes
    ttl:int

def ordinary_peer(address,local_ip,netmask):
    try:
        ip=ipaddress.IPv4Address(address);local=ipaddress.IPv4Address(local_ip)
        net=ipaddress.IPv4Network((local,netmask),strict=False)
        return (ip in net and ip not in (local,net.network_address,net.broadcast_address)
                and int(ip)>>24 not in (0,127) and not ip.is_link_local and int(ip)<0xe0000000)
    except (ValueError,TypeError,ipaddress.AddressValueError):return False

def request_shape(packet):
    return isinstance(packet,bytes) and len(packet)==REQUEST_BYTES and packet[:10]==MAGIC+bytes((VERSION,1))

class DiscoveryKey:
    """Scoped derived key. The already-loaded HTTP token is never retained."""
    __slots__=('_key',)
    def __init__(self,token):
        if (not isinstance(token,str) or not 1<=len(token)<=255 or token[0]==' ' or token[-1]==' '
                or any(not 0x20<=ord(c)<=0x7e or c==',' for c in token)):
            raise ProtocolError('unsupported_token_bytes')
        prk=hmac.digest(SALT,token.encode('utf-8'),'sha256')
        self._key=hmac.digest(prk,INFO+b'\x01','sha256')
    def close(self):self._key=None
    def _mac(self,prefix):
        if self._key is None:raise ProtocolError('discovery_key_unavailable')
        return hmac.digest(self._key,prefix,'sha256')
    def request(self,nonce):
        if not isinstance(nonce,bytes) or len(nonce)!=16:raise ProtocolError('invalid_nonce')
        prefix=MAGIC+bytes((VERSION,1))+nonce
        return prefix+self._mac(prefix)
    def verify_request(self,packet):
        if not request_shape(packet) or not hmac.compare_digest(self._mac(packet[:26]),packet[26:]):
            raise ProtocolError('invalid_request')
        return packet[10:26]
    def response(self,nonce,address,instance):
        if not isinstance(nonce,bytes) or len(nonce)!=16 or not isinstance(instance,bytes) or len(instance)!=16:
            raise ProtocolError('invalid_response_fields')
        try:packed=ipaddress.IPv4Address(address).packed
        except ValueError:raise ProtocolError('invalid_address') from None
        prefix=MAGIC+bytes((VERSION,2))+nonce+packed+struct.pack('!H',HTTP_PORT)+instance+struct.pack('!H',120)
        return prefix+self._mac(prefix)
    def verify_response(self,packet,*,source,nonce,local_ip,netmask):
        if (not isinstance(packet,bytes) or len(packet)!=RESPONSE_BYTES or packet[:10]!=MAGIC+bytes((VERSION,2))
                or len(nonce)!=16 or packet[10:26]!=nonce):raise ProtocolError('invalid_response')
        if not hmac.compare_digest(self._mac(packet[:50]),packet[50:]):raise ProtocolError('invalid_response')
        address=str(ipaddress.IPv4Address(packet[26:30]));port=struct.unpack('!H',packet[30:32])[0]
        ttl=struct.unpack('!H',packet[48:50])[0]
        if source!=(address,UDP_PORT) or port!=HTTP_PORT or not 30<=ttl<=120 or not ordinary_peer(address,local_ip,netmask):
            raise ProtocolError('invalid_origin')
        return Response(address,packet[32:48],ttl)
