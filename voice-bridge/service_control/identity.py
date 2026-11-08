"""Exact interpreter/script/creation-time classification; no process mutation."""
import os
import math
from pathlib import Path
import re


def normal(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def arguments(command):
    return [quoted or bare for quoted,bare in re.findall(r'"([^"]*)"|(\S+)',command or "")]


def invocation(record):
    args = arguments(record.get("CommandLine"))
    if not args:
        return None
    index = 1
    while index < len(args):
        if args[index] in {"-u","-B","-Xutf8","-I","-S"}:
            index += 1
        elif args[index:index+2] == ["-X","utf8"]:
            index += 2
        else:
            break
    if index >= len(args):
        return None
    return args[0],args[index],args[index+1:]


def base_interpreter(executable):
    path = Path(executable)
    try:
        text = (path.parent.parent/"pyvenv.cfg").read_text(encoding="utf-8")
        for line in text.splitlines():
            key,sep,value = line.partition("=")
            if sep and key.strip() == "executable":
                base = Path(value.strip())
                if path.name.lower() == "pythonw.exe":
                    base = base.with_name("pythonw.exe")
                return base if base.is_absolute() else None
    except OSError:
        pass
    return None


def classify(record, script, executable, records, *, base=None, sid=None):
    """owned/other/unknown; base argv is allowed only with a verified parent."""
    expected_exe,expected_script = normal(executable),normal(script)
    base = base or base_interpreter(executable)
    permitted = {expected_exe}
    if base is not None:
        permitted.add(normal(base))
    actual = record.get("ExecutablePath")
    if actual and normal(actual) not in permitted:
        return "other"
    # A readable, explicitly different invocation is negative evidence even
    # when a separate image query failed. It grants no ownership/stop rights.
    call = invocation(record)
    if call is not None:
        interpreter,script_slot,tail = call
        if script_slot == "-c":return "other"
        if Path(script_slot).is_absolute() and normal(script_slot)!=expected_script:return "other"
    if not actual:
        if record.get("Name", "").lower() not in {Path(x).name.lower() for x in permitted}:
            return "other"
        return "unknown"
    if call is None:
        return "unknown"
    interpreter,script_slot,_ = call
    if not Path(interpreter).is_absolute():
        return "unknown"
    if normal(interpreter) not in permitted:
        return "other"
    if not Path(script_slot).is_absolute():
        return "unknown" if Path(script_slot).name.lower() == Path(script).name.lower() else "other"
    if normal(script_slot) != expected_script:
        return "other"
    created = record.get("CreatedAt")
    if type(created) not in (int,float) or not math.isfinite(created) or created <= 0:
        return "unknown"
    if sid is not None and record.get("UserSid") != sid:
        return "unknown"
    if normal(actual) == expected_exe and normal(interpreter) == expected_exe:
        return "owned"
    if base is None or normal(actual) != normal(base) or normal(interpreter) not in permitted:
        return "other"
    parent = next((r for r in records if r.get("ProcessId") == record.get("ParentProcessId")),None)
    if parent is None:
        return "unknown"
    parent_call = invocation(parent)
    if (not parent.get("ExecutablePath") or normal(parent["ExecutablePath"]) != expected_exe
            or parent_call is None or normal(parent_call[0]) != expected_exe
            or not Path(parent_call[1]).is_absolute() or normal(parent_call[1]) != expected_script
            or parent_call[2] != call[2]):
        return "unknown"
    if (type(parent.get("CreatedAt")) not in (int,float) or not math.isfinite(parent["CreatedAt"])
            or not 0 < parent["CreatedAt"] <= created):
        return "unknown"
    if sid is not None and parent.get("UserSid") != sid:
        return "unknown"
    return "owned"


def component_identity(records, listeners, script, executable, *, sid=None, base=None):
    if records is None or listeners is None:
        return {"state":"UNKNOWN","reason":"进程或端口查询失败"}
    by_pid = {record["ProcessId"]:record for record in records}
    states = {record["ProcessId"]:classify(record,script,executable,records,base=base,sid=sid) for record in records}
    for pid in listeners:
        state = states.get(pid,"unknown")
        if state != "owned":
            return {"state":"CONFLICT" if state == "other" else "UNKNOWN",
                    "pid":pid,"reason":"端口归属冲突" if state == "other" else "监听进程身份未核验"}
    owned = [by_pid[pid] for pid,state in states.items() if state == "owned"]
    if listeners:
        record = by_pid[next(iter(listeners))]
    elif owned:
        record = max(owned,key=lambda item:item["CreatedAt"])
    elif "unknown" in states.values():
        return {"state":"UNKNOWN","reason":"可能相关进程元数据不可读或使用相对脚本"}
    else:
        return {"state":"ABSENT","reason":"完整查询确认不存在"}
    return {"state":"VERIFIED","pid":record["ProcessId"],"created_at":record["CreatedAt"],
            "executable":record["ExecutablePath"],"script":str(Path(script).resolve()),"reason":"精确身份已核验"}
