"""Public config refresh and existing-ledger adoption; no live control calls."""
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
import service_control.provider as module
from service_control.paths import ControlPaths


def cached_provider(tmp_path,monkeypatch):
    paths=ControlPaths(tmp_path,tmp_path/"state","fixture-sid")
    provider=module.WindowsProvider(paths)
    provider.voice_dir.mkdir()
    provider.cfg=SimpleNamespace(tts_primary="edge",tts_probe_interval_s=300)
    provider.ledger_loaded=True
    monkeypatch.setattr(provider,"_receipt",lambda:False)
    monkeypatch.setattr(module,"inventory",lambda:([],[]))
    import app.config
    monkeypatch.setattr(app.config,"load_config",lambda:pytest.fail("periodic refresh must not reload credentials"))
    return provider


def test_public_primary_refresh_and_real_mismatch_remains_visible(tmp_path,monkeypatch):
    provider=cached_provider(tmp_path,monkeypatch)
    config=provider.voice_dir/"config.yaml"
    config.write_text("tts:\n  primary: edge\n",encoding="utf-8")
    assert provider.begin() is None and provider.cfg.tts_primary=="edge"
    config.write_text("tts:\n  primary: mimo\n  probe_interval_s: 600\n",encoding="utf-8")
    assert provider.begin() is None and provider.cfg.tts_primary=="mimo" and provider.cfg.tts_probe_interval_s==600
    body={"tts":{"configured_primary":"mimo","active_engine":"mimo","last_probe_ok":True,"last_probe_ts":time.time()},
          "asr":"ready","device_auth":"ok","status":"ok"}
    assert module.voice_health(body,provider.cfg.tts_primary,600)["state"]=="READY"
    config.write_text("tts:\n  primary: edge\n",encoding="utf-8")
    assert provider.begin() is None
    assert module.voice_health(body,provider.cfg.tts_primary,300)["state"]=="DEGRADED"


@pytest.mark.parametrize("text",["tts: [mimo]","tts:\n  primary: bogus","tts:\n  primary: true",
    "tts:\n  primary: mimo\n  probe_interval_s: 0","tts:\n  primary: mimo\n  probe_interval_s: true",
    "tts:\n  primary: mimo\n  probe_interval_s: .nan","tts: [", "tts: {}"])
def test_bad_public_config_fails_instead_of_using_old_green(tmp_path,monkeypatch,text):
    provider=cached_provider(tmp_path,monkeypatch)
    (provider.voice_dir/"config.yaml").write_text(text,encoding="utf-8")
    assert provider.begin()["state"]=="FAILED"


def test_fresh_public_fields_reach_LAN_dependencies(tmp_path,monkeypatch):
    provider=cached_provider(tmp_path,monkeypatch)
    (provider.voice_dir/"config.yaml").write_text("tts:\n  primary: mimo\n",encoding="utf-8")
    assert provider.begin() is None
    observed=[]
    def inspect(cfg,*args,**kwargs):
        observed.append(cfg.tts_primary)
        return {"hermes":{"state":"READY"},"memory":{"state":"READY"},"discovery":{"state":"READY"}}
    monkeypatch.setattr(module,"observe_dependencies",inspect)
    provider.dependencies({"state":"READY","owner":"created","pid":1})
    assert observed==["mimo"]


@pytest.mark.parametrize("broken",[None,"launcher_missing","child_birth","sid","argv"])
def test_ledger_adopts_existing_children_without_original_manager_or_writes(tmp_path,monkeypatch,broken):
    paths=ControlPaths(tmp_path,tmp_path/"state","fixture-sid")
    paths.state_dir.mkdir()
    provider=module.WindowsProvider(paths);provider.owner="2"*32
    rows=[];groups={}
    for index,role in enumerate(module.ROLES):
        parent=10+index*10;child=parent+1;image=str(provider._executable(role))
        args=f'"{image}" "{provider.entry}" --service {role} --owner '+"1"*32
        rows.extend([dict(ProcessId=parent,ParentProcessId=999,ExecutablePath=image,Name="pythonw.exe",CommandLine=args,CreatedAt=100.,UserSid="fixture-sid"),
                     dict(ProcessId=child,ParentProcessId=parent,ExecutablePath=image,Name="pythonw.exe",CommandLine=args,CreatedAt=101.,UserSid="fixture-sid")])
        groups[role]={"pid":child,"created_at":101.,"launcher_pid":parent,"launcher_created_at":100.,"owner":"1"*32}
    if broken=="launcher_missing":rows=[r for r in rows if r["ProcessId"]!=10]
    elif broken=="child_birth":rows[1]["CreatedAt"]=102.
    elif broken=="sid":rows[1]["UserSid"]="other-fixture-sid"
    elif broken=="argv":rows[1]["CommandLine"]+=" unexpected"
    provider.records=rows
    ledger={"schema_version":1,"project_root":str(tmp_path.resolve()),"user_sid":"fixture-sid","groups":groups}
    paths.ledger.write_text(json.dumps(ledger),encoding="utf-8");before=paths.ledger.read_bytes()
    class Held:
        def __init__(self,record,**kwargs):self.pid=record["ProcessId"]
        def close(self):pass
    monkeypatch.setattr(module,"HeldProcess",Held)
    monkeypatch.setattr(provider,"_save",lambda:pytest.fail("adoption must not write ledger"))
    provider._load_ledger()
    if broken is None:
        assert set(provider.groups)==set(module.ROLES)
        assert all(item["owner"]=="1"*32 for item in provider.groups.values())
    else:assert "voice" not in provider.groups
    assert paths.ledger.read_bytes()==before
