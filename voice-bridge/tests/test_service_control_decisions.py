import json
import pytest
from service_control.checks import voice_health, choose_lan, data_capability, overall
from service_control.state import SnapshotReader, atomic_json
from service_control.core import ControlCore
from service_control.paths import ControlPaths


def healthy():
    return dict(status="ok",asr="ready",device_auth="ok",tts=dict(configured_primary="edge",active_engine="edge",last_probe_ok=True,last_probe_ts=100))


@pytest.mark.parametrize("field,value",[("status","degraded"),("asr","unavailable"),("device_auth","degraded"),
                                      ("last_probe_ok",False),("last_probe_ok",None),("last_probe_ts",None),
                                      ("last_probe_ts",500),("last_probe_ts",0),("active_engine","piper")])
def test_nonready_health_never_green(field,value):
    body=healthy()
    (body["tts"] if field in body["tts"] else body)[field]=value
    assert voice_health(body,"edge",300,now=401)["state"]!="READY"


def test_probe_age_boundary_and_no_private_payload_echo():
    assert voice_health(healthy(),"edge",300,now=430)["state"]=="READY"
    assert voice_health(healthy(),"edge",300,now=430.01)["state"]=="UNKNOWN"
    body=healthy();body["tts"]["last_probe_ok"]={"facts":"fixture-private","token":"fixture-secret"}
    assert "fixture-" not in json.dumps(voice_health(body,"edge",300,now=401))


def test_no_lan_is_independent_of_local_voice():
    voice=voice_health(healthy(),"edge",300,now=401)
    network=choose_lan([])
    assert voice["state"]=="READY" and network["state"]=="WAIT_NETWORK"
    components={key:{"state":"READY"} for key in ("voice","hermes","memory","memory_read")}
    components["discovery"]=network
    assert overall(components)=="DEGRADED"


def test_physical_interfaces_ambiguity_and_explicit_selection():
    rows=[dict(index=1,address="192.168.1.2",physical=True,up=True,description="WiFi",name="无线"),
          dict(index=2,address="10.0.0.2",physical=True,up=True,description="Ethernet",name="网线"),
          dict(index=3,address="172.16.0.1",physical=False,up=True,description="WSL",name="虚拟"),
          dict(index=4,address="169.254.1.2",physical=True,up=True,description="Ethernet"),
          dict(index=5,address="10.0.3.2",physical=True,up=True,description="VPN")]
    assert choose_lan(rows)["state"]=="UNKNOWN"
    assert choose_lan(rows,2)["selected"]["address"]=="10.0.0.2"
    assert choose_lan(rows,3)["state"]=="WAIT_NETWORK"


def test_data_local_capability_no_models_or_facts_in_result():
    body=dict(module_ready=True,hr_available=True,spo2_available=False,source_age_verified=True,
              facts="fixture-private",hr=75,token="fixture-secret")
    value=data_capability({"state":"READY"},body)
    assert value["state"]=="READY"
    assert all(key not in value for key in ("facts","hr","token"))
    assert data_capability({"state":"DEGRADED"},body)["state"]=="DEGRADED"
    assert data_capability({"state":"READY"},None)["state"]=="UNKNOWN"


def snapshot(project,sid):
    components={name:dict(state='READY',reason='fresh',last_check_at=100) for name in ('voice','discovery','hermes','memory_read','memory')}
    components['voice']['tts']=voice_health(healthy(),'edge',300,now=100)['tts']
    return dict(schema_version=1,snapshot_seq=1,core_instance_id="a"*32,core_pid=12,core_created_at=50,
                project_root=str(project.resolve()),user_sid=sid,updated_at=100,overall="READY",
                components=components)


@pytest.mark.parametrize("key,value",[("schema_version",2),("snapshot_seq",-1),("snapshot_seq",True),
    ("core_instance_id","b"*32),("core_pid",13),("core_created_at",51),("project_root","wrong"),
    ("user_sid","wrong"),("updated_at",200),("updated_at",True),("updated_at",float("nan")),
    ("overall","healthy"),("round_elapsed_s","wrong")])
def test_snapshot_rejects_invalid_or_unverified_identity(tmp_path,key,value):
    path=tmp_path/"state.json";state=snapshot(tmp_path,"fixture-sid")
    reader=SnapshotReader(tmp_path,"fixture-sid")
    reader.verify_identity({key:state[key] for key in ("core_instance_id","core_pid","core_created_at")})
    state[key]=value;atomic_json(path,state)
    assert reader.read(path,now=101)["overall"]=="UNKNOWN"


def test_same_snapshot_age_and_component_check_are_not_refreshed(tmp_path):
    path=tmp_path/"state.json";state=snapshot(tmp_path,"fixture-sid")
    reader=SnapshotReader(tmp_path,"fixture-sid")
    reader.verify_identity({key:state[key] for key in ("core_instance_id","core_pid","core_created_at")})
    atomic_json(path,state)
    assert reader.read(path,now=110)["overall"]=="READY"
    assert reader.read(path,now=110.01)["overall"]=="UNKNOWN"
    state.update(snapshot_seq=2,updated_at=190.01);atomic_json(path,state)
    assert reader.read(path,now=190.02)["components"]["voice"]["state"]=="UNKNOWN"
    state.update(snapshot_seq=1,updated_at=190.02);atomic_json(path,state)
    assert reader.read(path,now=190.03)["overall"]=="UNKNOWN"


def test_replace_failure_retains_previous_valid_snapshot(monkeypatch,tmp_path):
    path=tmp_path/"state.json";atomic_json(path,{"seq":1});before=path.read_bytes()
    def denied(*args):raise PermissionError("fixture denied")
    monkeypatch.setattr("service_control.state.os.replace",denied)
    with pytest.raises(PermissionError):atomic_json(path,{"seq":2})
    assert path.read_bytes()==before and not list(tmp_path.glob("*.tmp"))


class Provider:
    def __init__(self):self.groups={};self.starts=0;self.stops=[];self.owner=None
    def begin(self):return None
    def inspect(self,name):return {"state":"READY","lifecycle":"HEALTHY_CREATED"} if name in self.groups else {"state":"FAILED","lifecycle":"ABSENT"}
    def start(self,name):self.starts+=1;self.groups[name]=True;return {"state":"READY","lifecycle":"HEALTHY_CREATED"}
    def stop(self,name):self.stops.append(name);self.groups.pop(name,None)
    def created(self,name):return name in self.groups
    def created_summary(self):return [dict(name=name,pid={"voice":100,"mdns":101,"memory_service":102}[name],created_at=50,verified=True)
                                    for name in self.groups]
    def dependencies(self,voice):return {name:{"state":"READY","reason":"fixture"} for name in ("discovery","hermes","memory","memory_read")}


def test_concurrent_ensure_merges_and_status_has_no_mutations(tmp_path):
    import threading
    provider=Provider();core=ControlCore(ControlPaths(tmp_path,tmp_path,"fixture"),provider)
    threads=[threading.Thread(target=core.dispatch,args=({"request_id":str(i),"command":"ensure"},)) for i in range(5)]
    for t in threads:t.start()
    for t in threads:t.join()
    core.check();core.check()
    assert provider.starts==3
    before=(core.enabled,core.pending,dict(core.requests))
    core.dispatch({"request_id":"status","command":"status"})
    assert before==(core.enabled,core.pending,dict(core.requests))
    preview=core.dispatch({"request_id":"stop","command":"status"})
    core.dispatch({"request_id":preview["stop_preview_id"],"command":"stop"});core.stop_created()
    assert set(provider.stops)=={"voice","mdns","memory_service"}
    assert not core.dispatch({"request_id":"retry","command":"retry"})["accepted"]
    assert core.dispatch({"request_id":"new-start","command":"ensure"})["accepted"]


def test_recovery_cooldown_and_two_per_five_minutes_not_reset_by_retry(tmp_path):
    now=[100.0];core=ControlCore(ControlPaths(tmp_path,tmp_path,"fixture"),Provider(),clock=lambda:now[0])
    core.recoveries["voice"]=[90]
    assert not core.recovery_allowed("voice")
    now[0]=120;assert core.recovery_allowed("voice")
    core.recoveries["voice"].append(120);now[0]=200
    core.dispatch({"request_id":"retry","command":"retry"})
    assert not core.recovery_allowed("voice")
    now[0]=421;assert core.recovery_allowed("voice")


def test_stop_cannot_expand_to_objects_created_after_confirmation(tmp_path):
    provider=Provider();core=ControlCore(ControlPaths(tmp_path,tmp_path,"fixture"),provider)
    provider.start("voice")
    preview=core.dispatch({"request_id":"confirm","command":"status"})
    provider.start("mdns")
    assert core.dispatch({"request_id":preview["stop_preview_id"],"command":"stop"})["accepted"]
    core.stop_created()
    assert provider.stops==["voice"] and provider.created("mdns")


def test_unconfirmed_or_expired_stop_has_no_mutations(tmp_path):
    now=[100.0];core=ControlCore(ControlPaths(tmp_path,tmp_path,"fixture"),Provider(),clock=lambda:now[0])
    assert not core.dispatch({"request_id":"missing","command":"stop"})["accepted"]
    assert core.enabled and not core.stop_requested
    core.dispatch({"request_id":"old","command":"status"});now[0]+=121
    assert not core.dispatch({"request_id":"old","command":"stop"})["accepted"]
    assert core.enabled and not core.stop_requested
