"""Dependency decisions from bounded observations, without business calls."""
import ipaddress
import math
import time


def result(state, reason, **fields):
    return dict(state=state, reason=reason, **fields)


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def voice_health(body, primary, probe_interval, *, now=None):
    now = time.time() if now is None else now
    if not isinstance(body, dict):
        return result("UNKNOWN", "健康响应不可验证")
    if body.get('protocol')=='voice-v2':
        providers=body.get('providers')
        valid=isinstance(providers,dict) and all(isinstance(providers.get(k),dict) for k in ('asr','llm','tts'))
        if not valid:return result('UNKNOWN','v2健康字段缺失',protocol='voice-v2')
        ready=body.get('process_alive') is True and body.get('ready') is True and body.get('status')=='ok'
        ready=ready and all(providers[k].get('initialized') is True for k in ('asr','llm','tts'))
        ready=ready and providers['tts'].get('last_probe_ok') is True and providers['tts'].get('active_engine')==primary
        evidence=providers['tts'].get('last_probe_ts')
        fresh=(_finite_number(probe_interval) and probe_interval>0 and _finite_number(evidence)
               and 0<evidence<=now<=evidence+probe_interval+30)
        ready=ready and fresh
        return result('READY' if ready else 'DEGRADED','v2实际供应商已就绪' if ready else 'v2实际供应商未就绪',
                      protocol='voice-v2',process_alive=body.get('process_alive') is True,
                      tts=dict(configured_primary=primary,active_engine=providers['tts'].get('active_engine'),
                          last_probe_ok=providers['tts'].get('last_probe_ok'),last_probe_ts=evidence,
                          probe_interval_s=probe_interval,probe_expires_at=(evidence+probe_interval+30 if fresh else None)),
                      v2_readiness=dict(asr_initialized=providers['asr'].get('initialized') is True,
                          llm_initialized=providers['llm'].get('initialized') is True,
                          tts_initialized=providers['tts'].get('initialized') is True,
                          tts_probe_ok=providers['tts'].get('last_probe_ok') is True,
                          configured_primary=primary,active_engine=providers['tts'].get('active_engine')))
    tts = body.get("tts")
    if not isinstance(tts, dict):
        return result("UNKNOWN", "TTS健康字段缺失")
    details = {key:tts.get(key) for key in ("configured_primary", "active_engine", "last_probe_ok", "last_probe_ts")}
    for key in ("configured_primary","active_engine"):
        if details[key] not in ("edge","piper","mimo",None):details[key]=None
    if type(details["last_probe_ok"]) is not bool:details["last_probe_ok"]=None
    if type(details["last_probe_ts"]) not in (float,int):details["last_probe_ts"]=None
    if details["last_probe_ts"] is not None and not _finite_number(details["last_probe_ts"]):details["last_probe_ts"]=None
    valid_period=_finite_number(probe_interval) and probe_interval>0
    details['probe_interval_s']=probe_interval if valid_period else None
    stamp=details['last_probe_ts']
    details['probe_expires_at']=(stamp+probe_interval+30 if valid_period and stamp is not None and stamp>0 else None)
    if not valid_period or (details['probe_expires_at'] is not None and not _finite_number(details['probe_expires_at'])):
        details['probe_expires_at']=None
        return result('UNKNOWN','TTS探测周期不可验证',tts=details)
    if details["configured_primary"] != primary or details["active_engine"] != primary:
        return result("DEGRADED", "TTS配置与实际引擎不一致", tts=details)
    stamp = details["last_probe_ts"]
    if type(stamp) not in (int,float) or not _finite_number(stamp) or stamp<=0 or stamp > now or now > details['probe_expires_at']:
        return result("UNKNOWN", "TTS最近探测缺失或过期", tts=details)
    if details["last_probe_ok"] is not True:
        return result("DEGRADED", "TTS最近合成探测失败", tts=details)
    for key, expected, reason in (("asr", "ready", "ASR未就绪"),
                                  ("device_auth", "ok", "设备鉴权未就绪"),
                                  ("status", "ok", "语音健康状态未就绪")):
        if body.get(key) != expected:
            return result("DEGRADED", reason, tts=details)
    return result("READY", "本机语音健康字段全部通过", tts=details)


def lan_candidates(records):
    accepted = []
    for record in records:
        try:
            address = ipaddress.ip_address(record["address"])
            description = str(record.get("description", "")).lower()
            if (address.version != 4 or address.is_loopback or address.is_link_local
                    or address.is_unspecified or record.get("physical") is not True
                    or record.get("up") is not True
                    or any(word in description for word in ("vpn", "wsl", "virtual", "vethernet", "tap", "tun"))):
                continue
            accepted.append({"index":int(record["index"]), "address":str(address),
                             "name":str(record.get("name", ""))[:80]})
        except (ValueError, KeyError, TypeError):
            continue
    return accepted


def choose_lan(records, selected=None):
    candidates = lan_candidates(records)
    if selected is not None:
        candidates = [item for item in candidates if item["index"] == selected]
    if not candidates:
        return result("WAIT_NETWORK", "没有可用的物理LAN网卡", candidates=[])
    if len(candidates) != 1:
        return result("UNKNOWN", "多个LAN候选，请选择设备所在网卡", candidates=candidates)
    return result("READY", "已选择物理LAN网卡", selected=candidates[0], candidates=candidates)


def data_capability(voice, body):
    required = ("module_ready", "hr_available", "spo2_available", "source_age_verified")
    if not isinstance(body,dict) or not all(type(body.get(key)) is bool for key in required):
        return result("UNKNOWN", "DATA状态接口未启用、未授权或响应不可验证")
    available = body["module_ready"] and (body["hr_available"] or body["spo2_available"])
    state = "READY" if voice["state"] == "READY" and available else "DEGRADED"
    return result(state, "本地健康数据直答可用" if state == "READY" else "语音或本地有效数据未就绪",
                  **{key:body[key] for key in required})


def overall(components):
    critical = components.get("voice", {})
    if critical.get("state") in ("FAILED", "CONFLICT", "UNKNOWN", "STARTING", "CHECKING", "STOPPED"):
        return critical["state"]
    required = ("voice", "discovery") if critical.get('protocol')=='voice-v2' else ("voice", "discovery", "hermes", "memory_read", "memory")
    return "READY" if all(components.get(key,{}).get("state") == "READY" for key in required) else "DEGRADED"
