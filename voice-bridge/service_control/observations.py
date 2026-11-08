"""GET-only, direct, bounded observations. Credentials/body stay in memory."""
import json
import http.client
import ipaddress
from pathlib import Path
import socket
import threading
import time
import urllib.parse
import math,re
from .checks import voice_health, result, data_capability, choose_lan
from .processes import adapters


def get_json(url, *, token=None, device_token=None):
    """Direct local/LAN HTTP, no redirects, 64KiB and a total 3s I/O budget."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password:
        return None
    host='127.0.0.1' if parsed.hostname=='localhost' else parsed.hostname
    try:ipaddress.ip_address(host)
    except ValueError:return None  # fixed probes use numeric IPs, never DNS wait
    headers = {}
    if token:headers["Authorization"] = "Bearer " + token
    if device_token:headers["X-Device-Token"] = device_token
    connection=timer=None
    try:
        started=time.monotonic()
        connection=http.client.HTTPConnection(host,parsed.port or 80,timeout=3)
        connection.connect()
        remaining=3-(time.monotonic()-started)
        if remaining<=0:return None
        owned_socket=connection.sock
        def abort():
            try:owned_socket.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        # Per-read socket timeouts alone allow a byte-dripping peer to hold the
        # worker indefinitely. Shutdown only this owned probe socket at deadline.
        timer=threading.Timer(remaining,abort);timer.daemon=True;timer.start()
        path=parsed.path or '/'
        if parsed.query:path+='?'+parsed.query
        connection.request('GET',path,headers=headers)
        with connection.getresponse() as response:
            if response.status != 200:return None
            body = response.read(65537)
            if len(body)>65536:return None
            return json.loads(body.decode("utf-8"))
    except (OSError,ValueError,RecursionError):return None
    except http.client.HTTPException:return None
    finally:
        if timer is not None:timer.cancel()
        if connection is not None:connection.close()


def mdns_observation(address):
    from zeroconf import Zeroconf, DNSOutgoing, DNSQuestion
    from zeroconf.const import _FLAGS_QR_QUERY, _TYPE_TXT, _CLASS_IN
    deadline = time.monotonic() + 5.0
    zc = Zeroconf(interfaces=[address])
    name = "voicebridge._voicebridge._tcp.local."
    next_txt_query = 0.0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining < 0.001:
                return result("DEGRADED", "实际mDNS记录缺失或不匹配")
            info = zc.get_service_info("_voicebridge._tcp.local.", name,
                                       timeout=int(remaining * 1000))
            now = time.monotonic()
            if now >= deadline:
                return result("DEGRADED", "实际mDNS记录缺失或不匹配")
            if info is not None:
                if (info.server != "voicebridge.local." or info.port != 8710
                        or address not in info.parsed_addresses()):
                    return result("DEGRADED", "实际mDNS记录缺失或不匹配")
                properties = info.properties
                if b"app" in properties:
                    if properties[b"app"] != b"voice-bridge":
                        return result("DEGRADED", "实际mDNS记录缺失或不匹配")
                    return result("READY", "当前LAN的mDNS记录已核验", address=address)
            # A/SRV may be cached before TXT. Explicitly request the missing
            # record; get_service_info alone can return that partial cache.
            if now >= next_txt_query:
                query = DNSOutgoing(_FLAGS_QR_QUERY)
                query.add_question(DNSQuestion(name, _TYPE_TXT, _CLASS_IN))
                zc.send(query)
                next_txt_query = now + 0.5
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.1, remaining))
    finally:
        zc.close()


def selected_voice_health(cfg,base):
    v2=getattr(cfg,'voice_v2_enabled',False) is True
    return get_json(base+('/api/v2/voice/health' if v2 else '/api/v1/health'),
                    device_token=cfg.device_token() if v2 else None)

def box_link_observation(body,*,observed_at=None):
    if not isinstance(body,dict):return result('UNKNOWN','未取得真实BOX回执')
    link=body.get('box_link');instance=body.get('pc_instance')
    if not isinstance(link,dict) or not isinstance(instance,str) or not re.fullmatch('[0-9a-f]{32}',instance):
        return result('UNKNOWN','BOX回执字段缺失')
    age=link.get('last_box_health_age');epoch=link.get('origin_epoch')
    fresh=type(age) in (int,float) and math.isfinite(age) and 0<=age<45
    valid_epoch=type(epoch) is int and 0<epoch<=0xffffffffffffffff
    ready=fresh and valid_epoch and link.get('health_ready') is True and link.get('session_registered') is True and link.get('state')=='READY'
    return result('READY' if ready else ('DEGRADED' if fresh else 'UNKNOWN'),
                  '真实BOX健康及会话回执新鲜' if ready else 'BOX健康/会话回执未齐或已过期',
                  origin_epoch=epoch if valid_epoch else None,health_age_s=age if fresh else None,pc_instance=instance,
                  health_expires_at=(time.time() if observed_at is None else observed_at)+45-age if fresh else None)


def observe_dependencies(cfg, paths, voice, *, gateway_identity=False, memory_identity=False, voice_identity=False):
    """Purely observational; no POST/chat/TTS/knowledge/health update calls."""
    try:
        selected = json.loads(paths.settings.read_text(encoding="utf-8")).get("interface_index")
        if type(selected) is not int:selected=None
    except (OSError,ValueError,AttributeError):selected=None
    try:network = choose_lan(adapters(),selected)
    except (OSError,ValueError):network = result("UNKNOWN","LAN网卡查询不可验证",candidates=[])
    discovery = dict(network);lan_body=None;lan_started=time.time()
    if network["state"] == "READY":
        address = network["selected"]["address"]
        lan_started=time.time()
        lan_body=selected_voice_health(cfg,f"http://{address}:8710")
        lan = voice_health(lan_body,cfg.tts_primary,cfg.tts_probe_interval_s)
        try:advertisement=mdns_observation(address)
        except (OSError,ValueError,ImportError):advertisement=result("UNKNOWN","mDNS观察不可验证")
        discovery = result("READY" if lan["state"]==advertisement["state"]=="READY" else "DEGRADED",
                           "LAN健康及广告通过" if lan["state"]==advertisement["state"]=="READY" else "LAN健康或广告未就绪",
                           selected=network["selected"],candidates=network["candidates"],lan_state=lan["state"],mdns_state=advertisement["state"])
    token = cfg.llm_api_key()
    gateway_url = urllib.parse.urlsplit(cfg.llm_api_server_url)
    allowed = (gateway_url.scheme=="http" and gateway_url.hostname in ("127.0.0.1","localhost","::1")
               and gateway_url.port==8780 and gateway_url.path.rstrip('/')=="/v1"
               and not gateway_url.username and not gateway_url.password and not gateway_url.query and not gateway_url.fragment)
    gateway = get_json("http://127.0.0.1:8780/health") if allowed else None
    models = get_json("http://127.0.0.1:8780/v1/models",token=token) if allowed and token and gateway_identity else None
    gateway_ok = isinstance(gateway,dict) and gateway.get("status") == "ok"
    auth_ok = isinstance(models,dict) and isinstance(models.get("data"),list)
    hermes = result("READY" if gateway_ok and auth_ok else "DEGRADED",
                    "网关健康与只读访问通过" if gateway_ok and auth_ok else "网关或调用鉴权未验证",
                    gateway_healthy=gateway_ok,access_verified=auth_ok)
    memory_url = urllib.parse.urlsplit(cfg.memory_api_url)
    allowed_memory = (memory_url.scheme=="http" and memory_url.hostname in ("127.0.0.1","localhost","::1")
                      and memory_url.port==8781 and memory_url.path.rstrip('/')=="/api/v1/memory"
                      and not memory_url.username and not memory_url.password and not memory_url.query and not memory_url.fragment)
    memory_body = get_json(cfg.memory_api_url,token=token) if token and allowed_memory and memory_identity else None
    memory_ok = isinstance(memory_body,dict) and memory_body.get("ok") is True
    memory = result("READY" if memory_ok else "DEGRADED","记忆只读鉴权通过" if memory_ok else "记忆写删访问未就绪或未配置鉴权",
                    credential_present=bool(token),access_verified=memory_ok)
    # No memory body (including facts), raw model listing or credentials escapes.
    del memory_body, models
    readable = all(path.is_file() and __import__("os").access(path,__import__("os").R_OK)
                   for path in (cfg.user_profile_path,cfg.memory_file_path))
    device_token = cfg.device_token()
    data = get_json("http://127.0.0.1:8710/api/v1/health/data/status",device_token=device_token) if device_token and voice_identity else None
    udp=lan_body.get('discovery_udp') if isinstance(lan_body,dict) else None
    udp_ready=isinstance(udp,dict) and udp.get('listener')=='LISTENING'
    udp_status=result('READY' if udp_ready else 'UNKNOWN','PC配对发现监听已就绪；BOX另验' if udp_ready else '未取得PC配对发现监听证据')
    return {"discovery":discovery,"udp_discovery":udp_status,"box_link":box_link_observation(lan_body,observed_at=lan_started),"hermes":hermes,"memory":memory,
            "memory_read":result("READY" if readable else "DEGRADED","本地记忆文件可读" if readable else "本地画像或记忆文件缺失/不可读"),
            "deepseek":result("UNKNOWN","已配置，模型请求未验证" if cfg.lightweight_api_key() else "轻量通道未配置",
                              configured=bool(cfg.lightweight_api_key()),request_verified=False),
            "data":data_capability(voice,data)}
