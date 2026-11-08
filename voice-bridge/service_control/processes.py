"""Read-only inventory and exact held-handle identity. Never kill by port/name."""
import ctypes as C
from ctypes import wintypes as W
import json
import subprocess
import time
from pathlib import Path
from .windows import k, check, close, process_created, process_sid, process_image, api, native_process_record, native_process_observation, process_entries
from .identity import normal, classify, invocation

NO_WINDOW = 0x08000000


def powershell_json(script):
    prefix = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$ErrorActionPreference='Stop';"
    completed = subprocess.run(["pwsh.exe", "-NoLogo", "-NoProfile", "-Command", prefix + script],
                               capture_output=True, timeout=8, creationflags=NO_WINDOW)
    if completed.returncode:
        raise OSError("CIM/adapter query failed")
    if len(completed.stdout) > 4 * 1024 * 1024:
        raise ValueError("inventory response exceeds bound")
    return json.loads(completed.stdout.decode("utf-8-sig"))


def inventory():
    try:
        started=time.monotonic();records=[];partial=False
        for hint in process_entries():
            if hint['Name'].lower() not in ('python','pythonw','python.exe','pythonw.exe'):continue
            try:
                record=native_process_record(hint['ProcessId'])
                if record['ParentProcessId']!=hint['ParentProcessId']:raise ValueError('snapshot parent changed')
            except (OSError,ValueError):
                # A failed SID/image query must not erase independent command
                # or image evidence. All partial fields share a held birth.
                record=native_process_observation(hint);partial=True
                if record.get('ExitedConfirmed') is True:continue
            records.append(record)
            if time.monotonic()-started>8:raise TimeoutError('native inventory budget exceeded')
        if partial:
            # One bounded complete resnapshot can confirm a race exit. Access
            # denied with a still-present PID remains an opaque candidate.
            present={entry['ProcessId'] for entry in process_entries()}
            records=[record for record in records if record['ProcessId'] in present]
        listeners=[r for r in native_listeners() if r['LocalPort'] in (8710,8780,8781)]
        if time.monotonic()-started>8:raise TimeoutError('native inventory budget exceeded')
        return records,listeners
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):
        return None, None


def peer_record(pid):
    """Double-read the exact IPC peer; parent is optional identity evidence."""
    pid = int(pid)
    started=time.monotonic();record=native_process_record(pid)
    parent=None
    try:
        candidate=native_process_record(record['ParentProcessId'])
        born=candidate.get('CreatedAt')
        if (candidate.get('ProcessId')==record['ParentProcessId']!=pid
                and type(born) in (int,float) and 0<born<=record['CreatedAt']):
            parent=candidate
    except (OSError,ValueError):
        pass  # Missing parent never substitutes for either complete child read.
    again=native_process_record(pid)
    if again!=record or time.monotonic()-started>8:
        raise ValueError('IPC peer/parent exited, changed or exceeded query budget')
    return [record,parent] if parent is not None else [record]


def verify_peer(pid, paths, script, executable, *, required_args=None):
    records = peer_record(pid)
    record = next((item for item in records if item["ProcessId"] == pid),None)
    if record is None or classify(record,script,executable,records,sid=paths.sid) != "owned":
        raise ValueError("IPC peer identity unverified")
    if required_args is not None and invocation(record)[2] != list(required_args):
        raise ValueError("IPC peer arguments differ")
    return record


class HeldProcess:
    def __init__(self, record, *, sid):
        self.pid = int(record["ProcessId"])
        self.created = record["CreatedAt"]
        self.executable = record["ExecutablePath"]
        self.sid = sid
        self.command_line = record.get("CommandLine")
        self.parent_pid = record.get("ParentProcessId")
        self.handle = check(k.OpenProcess(0x100001 | 0x1000,False,self.pid))
        try:self.verify()
        except BaseException:
            self.close();raise

    def alive(self):
        return k.WaitForSingleObject(self.handle,0) == 258

    def verify(self):
        record=native_process_record(self.pid,handle=self.handle)
        if (record['CreatedAt']!=self.created or record['UserSid']!=self.sid
                or normal(record['ExecutablePath'])!=normal(self.executable)
                or self.command_line is None or record['CommandLine']!=self.command_line
                or self.parent_pid is None or record['ParentProcessId']!=self.parent_pid):
            raise ValueError("held process identity changed or exited")

    def terminate(self):
        if not self.alive():return
        self.verify()
        check(k.TerminateProcess(self.handle,1))
        if k.WaitForSingleObject(self.handle,3000) == 258:
            raise TimeoutError("directed termination still pending")

    def close(self):
        close(self.handle);self.handle=None


def adapters():
    from .native_adapters import adapters as native_adapters
    return native_adapters()


def native_listeners():
    """Read kernel IPv4/IPv6 listener owners, never connect or change sockets."""
    import socket
    iphlp=C.WinDLL('iphlpapi',use_last_error=True)
    query=api(iphlp,'GetExtendedTcpTable',W.DWORD,
              [C.c_void_p,C.POINTER(W.DWORD),W.BOOL,W.ULONG,C.c_int,W.ULONG])
    class Row4(C.Structure):
        _fields_=[('state',W.DWORD),('local',W.DWORD),('port',W.DWORD),
                  ('remote',W.DWORD),('remote_port',W.DWORD),('pid',W.DWORD)]
    class Row6(C.Structure):
        _fields_=[('local',W.BYTE*16),('local_scope',W.DWORD),('port',W.DWORD),
                  ('remote',W.BYTE*16),('remote_scope',W.DWORD),('remote_port',W.DWORD),
                  ('state',W.DWORD),('pid',W.DWORD)]
    rows=[]
    for family,row_type in ((2,Row4),(23,Row6)):
        size=W.DWORD();code=query(None,C.byref(size),False,family,3,0)
        if code!=122 or not 4<=size.value<=4*1024*1024:raise OSError('native listener size unavailable')
        buffer=C.create_string_buffer(size.value)
        code=query(buffer,C.byref(size),False,family,3,0)
        if code or not 4<=size.value<=len(buffer):raise OSError('native listener table unavailable')
        count=W.DWORD.from_buffer(buffer).value
        if 4+count*C.sizeof(row_type)>size.value:raise ValueError('native listener table bounds invalid')
        for index in range(count):
            row=row_type.from_buffer(buffer,4+index*C.sizeof(row_type))
            if row.state!=2:raise ValueError('non-listener in native listener table')
            rows.append(dict(LocalPort=socket.ntohs(row.port&0xffff),OwningProcess=int(row.pid)))
    return rows
