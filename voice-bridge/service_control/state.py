"""Atomic, freshness-checked control snapshots; no business data."""
import json
import math
import re
import os
from pathlib import Path
import time
import uuid

STATES = frozenset({"CHECKING", "STARTING", "READY", "DEGRADED", "FAILED", "CONFLICT", "UNKNOWN", "STOPPED", "WAIT_NETWORK"})
CORE_MAX_AGE = 10
COMPONENT_MAX_AGE = 90


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def atomic_json(path, value, *, secure=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        if secure:
            secure(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class SnapshotReader:
    def __init__(self, project, sid):
        self.project = str(Path(project).resolve())
        self.sid = sid
        self.identity = None
        self.sequence = -1

    def verify_identity(self, identity):
        if self.identity != identity:
            self.sequence = -1
        self.identity = dict(identity)

    def read(self, path, now=None):
        try:
            with Path(path).open('rb') as source:raw=source.read(128*1024+1)
            if len(raw) > 128 * 1024:
                raise ValueError("state too large")
            state = json.loads(raw.decode("utf-8"))
            now = time.time() if now is None else now
            required = {"schema_version", "snapshot_seq", "core_instance_id", "core_pid", "core_created_at", "project_root", "user_sid", "updated_at", "components", "overall"}
            if not isinstance(state, dict) or not required <= set(state):
                raise ValueError("missing state fields")
            if type(state["schema_version"]) is not int or state["schema_version"] != 1:
                raise ValueError("unknown schema version")
            if type(state["snapshot_seq"]) is not int or state["snapshot_seq"] < 0 or state["snapshot_seq"] < self.sequence:
                raise ValueError("snapshot sequence rollback")
            if (type(state["core_pid"]) is not int or state["core_pid"]<=0
                    or not isinstance(state["core_instance_id"],str)
                    or re.fullmatch(r"[0-9a-f]{32}",state["core_instance_id"]) is None
                    or type(state["core_created_at"]) not in (float,int)
                    or not _finite_number(state["core_created_at"]) or not 0<state["core_created_at"]<=now):
                raise ValueError("invalid core identity")
            if state["project_root"] != self.project or state["user_sid"] != self.sid:
                raise ValueError("project/user mismatch")
            if self.identity is None or any(state[key] != value for key, value in self.identity.items()):
                raise ValueError("core identity unverified or changed")
            stamp = state["updated_at"]
            if type(stamp) not in (float, int) or not _finite_number(stamp) or not 0<stamp<=now:
                raise ValueError("invalid/future timestamp")
            if now - stamp > CORE_MAX_AGE:
                raise ValueError("状态过期")
            if state["overall"] not in STATES or not isinstance(state["components"], dict):
                raise ValueError("invalid status")
            components=state['components']
            if any(not isinstance(component,dict) for component in components.values()):
                raise ValueError('invalid raw component type')
            if state['overall']=='READY':
                required_ready=('voice','discovery') if components.get('voice',{}).get('protocol')=='voice-v2' else ('voice','discovery','hermes','memory_read','memory')
                if any(not isinstance(components.get(name),dict) or components[name].get('state')!='READY' for name in required_ready):
                    raise ValueError('READY readiness components missing or contradictory')
            voice=components.get('voice')
            v2=isinstance(voice,dict) and voice.get('protocol')=='voice-v2'
            if v2:
                evidence=voice.get('v2_readiness')
                if voice.get('state')=='READY':
                    if voice.get('process_alive') is not True or not isinstance(evidence,dict):
                        raise ValueError('READY v2 initialization evidence missing')
                    if any(evidence.get(key) is not True for key in ('asr_initialized','llm_initialized','tts_initialized','tts_probe_ok')):
                        raise ValueError('READY v2 initialization evidence invalid')
                    if evidence.get('configured_primary') not in ('edge','mimo') or evidence.get('active_engine')!=evidence['configured_primary']:
                        raise ValueError('READY v2 TTS engine evidence invalid')
            if isinstance(voice,dict) and voice.get('state')=='READY' and 'tts' not in voice:
                raise ValueError('READY voice TTS evidence missing')
            for name in ("phase","reason"):
                if name in state and (not isinstance(state[name],str) or len(state[name])>1000):raise ValueError("invalid display text")
            elapsed=state.get("round_elapsed_s",0)
            if type(elapsed) not in (float,int) or not _finite_number(elapsed) or elapsed<0:raise ValueError("invalid elapsed time")
            result = dict(state)
            result["components"] = {name:dict(component) for name, component in state["components"].items()}
            for name,component in result["components"].items():
                if not isinstance(component, dict) or component.get("state") not in STATES:
                    raise ValueError("invalid component")
                if not isinstance(component.get("reason",""),str):raise ValueError("invalid component reason")
                if name=='box_link' and component['state']=='READY':
                    expiry=component.get('health_expires_at')
                    if not _finite_number(expiry) or not now<expiry<=now+45:
                        component.update(state='UNKNOWN',reason='BOX回执有效期缺失或已过期')
                if 'tts' in component:
                    tts=component['tts']
                    required_tts={'configured_primary','active_engine','last_probe_ok','last_probe_ts','probe_interval_s','probe_expires_at'}
                    if not isinstance(tts,dict) or not required_tts <= tts.keys():raise ValueError('invalid TTS snapshot')
                    if any(tts[key] is not None and not isinstance(tts[key],str) for key in ('configured_primary','active_engine')):
                        raise ValueError('invalid TTS engine')
                    if tts['last_probe_ok'] is not None and type(tts['last_probe_ok']) is not bool:raise ValueError('invalid TTS probe')
                    probe=tts['last_probe_ts']
                    if probe is not None and (type(probe) not in (int,float) or not _finite_number(probe) or not 0<probe<=now):
                        raise ValueError('invalid TTS probe timestamp')
                    claims_ready = component['state']=='READY' or state['overall']=='READY'
                    if claims_ready and (tts['last_probe_ok'] is not True or probe is None
                            or not tts['configured_primary'] or not tts['active_engine']
                            or tts['configured_primary'] != tts['active_engine']):
                        raise ValueError('TTS snapshot readiness contradicts probe/engine')
                    period,expiry=tts['probe_interval_s'],tts['probe_expires_at']
                    if period is not None and (type(period) not in (int,float) or not _finite_number(period) or period<=0):
                        raise ValueError('invalid TTS probe interval')
                    if expiry is not None and (type(expiry) not in (int,float) or not _finite_number(expiry) or expiry<=0
                            or period is None or probe is None or not math.isclose(expiry,probe+period+30,rel_tol=0,abs_tol=1e-6)):
                        raise ValueError('invalid TTS probe expiry')
                    if claims_ready and (period is None or expiry is None):raise ValueError('READY TTS expiry evidence missing')
                    if expiry is not None and now>expiry:raise ValueError('TTS探测过期')
                checked = component.get("last_check_at")
                if checked is not None and (type(checked) not in (float, int) or not _finite_number(checked) or not 0<=checked<=now):
                    raise ValueError("invalid component timestamp")
                if checked is None or now - checked > COMPONENT_MAX_AGE:
                    component.update(state="UNKNOWN", reason="组件检查过期")
                    result["overall"] = "UNKNOWN"
            # Only a fully validated snapshot may advance the reader watermark.
            self.sequence = state["snapshot_seq"]
            return result
        except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
            return {"overall":"UNKNOWN", "reason":str(error), "components":{}, "valid":False}
