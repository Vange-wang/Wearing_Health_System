"""Small Windows primitives: current-user ACL, mutex, bounded local pipes."""
import ctypes as C
from ctypes import wintypes as W
import os
import time
from pathlib import Path

if os.name != "nt":
    raise RuntimeError("service control requires Windows")

k = C.WinDLL("kernel32", use_last_error=True)
a = C.WinDLL("advapi32", use_last_error=True)
u = C.WinDLL("user32", use_last_error=True)
INVALID_HANDLE = C.c_void_p(-1).value


def api(dll, name, result, args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = args
    return function


api(k, "GetCurrentProcess", W.HANDLE, [])
api(k, "OpenProcess", W.HANDLE, [W.DWORD,W.BOOL,W.DWORD])
api(k, "QueryFullProcessImageNameW", W.BOOL, [W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)])
api(k, "TerminateProcess", W.BOOL, [W.HANDLE,W.UINT])
api(k, "OpenMutexW", W.HANDLE, [W.DWORD,W.BOOL,W.LPCWSTR])
api(k, "CloseHandle", W.BOOL, [W.HANDLE])
api(k, "GetProcessTimes", W.BOOL, [W.HANDLE,C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME)])
api(k, "CreateMutexW", W.HANDLE, [C.c_void_p,W.BOOL,W.LPCWSTR])
api(k, "ReleaseMutex", W.BOOL, [W.HANDLE])
api(k, "CreateEventW", W.HANDLE, [C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR])
api(k, "WaitForSingleObject", W.DWORD, [W.HANDLE,W.DWORD])
api(k, "LocalFree", C.c_void_p, [C.c_void_p])
api(a, "OpenProcessToken", W.BOOL, [W.HANDLE,W.DWORD,C.POINTER(W.HANDLE)])
api(a, "GetTokenInformation", W.BOOL, [W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)])
api(a, "ConvertSidToStringSidW", W.BOOL, [C.c_void_p,C.POINTER(W.LPWSTR)])
api(a, "ConvertStringSecurityDescriptorToSecurityDescriptorW", W.BOOL, [W.LPCWSTR,W.DWORD,C.POINTER(C.c_void_p),C.POINTER(W.DWORD)])
api(a, "SetFileSecurityW", W.BOOL, [W.LPCWSTR,W.DWORD,C.c_void_p])
api(k, "GetNamedPipeServerProcessId", W.BOOL, [W.HANDLE,C.POINTER(W.ULONG)])


def check(value):
    if not value:
        raise C.WinError(C.get_last_error())
    return value


def close(handle):
    if handle and handle != INVALID_HANDLE:
        k.CloseHandle(handle)


def process_created(pid):
    handle = k.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        created, exited, kernel, user = W.FILETIME(),W.FILETIME(),W.FILETIME(),W.FILETIME()
        check(k.GetProcessTimes(handle,C.byref(created),C.byref(exited),C.byref(kernel),C.byref(user)))
        return ((created.dwHighDateTime << 32) | created.dwLowDateTime) / 10_000_000 - 11644473600
    finally:
        close(handle)


def process_sid(pid=None):
    process = k.GetCurrentProcess() if pid is None else check(k.OpenProcess(0x1000,False,int(pid)))
    token = W.HANDLE()
    try:check(a.OpenProcessToken(process,8,C.byref(token)))
    finally:
        if pid is not None:close(process)
    try:
        size = W.DWORD()
        a.GetTokenInformation(token,1,None,0,C.byref(size))
        buffer = C.create_string_buffer(size.value)
        check(a.GetTokenInformation(token,1,buffer,size,C.byref(size)))
        sid_pointer = C.cast(buffer,C.POINTER(C.c_void_p))[0]
        text = W.LPWSTR()
        check(a.ConvertSidToStringSidW(sid_pointer,C.byref(text)))
        try:return text.value
        finally:k.LocalFree(text)
    finally:
        close(token)


def current_sid():
    return process_sid()


def process_image(pid):
    handle = check(k.OpenProcess(0x1000,False,int(pid)))
    try:
        buffer = C.create_unicode_buffer(32768); size = W.DWORD(len(buffer))
        check(k.QueryFullProcessImageNameW(handle,0,buffer,C.byref(size)))
        return buffer.value
    finally:close(handle)


def manager_exists(name):
    handle = k.OpenMutexW(0x100000,False,name)
    if handle:
        close(handle); return True
    error = C.get_last_error()
    if error == 2:return False
    raise C.WinError(error)  # unreadable is not absent


class Security:
    def __init__(self, sid):
        self.sid = sid
        self.sddl = f"D:P(A;;GA;;;{sid})"
        self.pointer = C.c_void_p()
        check(a.ConvertStringSecurityDescriptorToSecurityDescriptorW(self.sddl,1,C.byref(self.pointer),None))

    def close(self):
        if self.pointer:
            k.LocalFree(self.pointer)
            self.pointer = C.c_void_p()

    def secure_file(self, path):
        check(a.SetFileSecurityW(str(path),0x80000004,self.pointer))


class Attributes(C.Structure):
    _fields_ = [("length",W.DWORD),("descriptor",C.c_void_p),("inherit",W.BOOL)]


class Overlapped(C.Structure):
    _fields_ = [("internal",C.c_size_t),("internal_high",C.c_size_t),
                ("offset",W.DWORD),("offset_high",W.DWORD),("event",W.HANDLE)]


api(k,"CreateNamedPipeW",W.HANDLE,[W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,C.POINTER(Attributes)])
api(k,"ConnectNamedPipe",W.BOOL,[W.HANDLE,C.POINTER(Overlapped)])
api(k,"DisconnectNamedPipe",W.BOOL,[W.HANDLE])
api(k,"ReadFile",W.BOOL,[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.POINTER(Overlapped)])
api(k,"WriteFile",W.BOOL,[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.POINTER(Overlapped)])
api(k,"GetOverlappedResult",W.BOOL,[W.HANDLE,C.POINTER(Overlapped),C.POINTER(W.DWORD),W.BOOL])
api(k,"CancelIoEx",W.BOOL,[W.HANDLE,C.POINTER(Overlapped)])
api(k,"CreateFileW",W.HANDLE,[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE])
api(k,"WaitNamedPipeW",W.BOOL,[W.LPCWSTR,W.DWORD])
api(k,"SetNamedPipeHandleState",W.BOOL,[W.HANDLE,C.POINTER(W.DWORD),C.c_void_p,C.c_void_p])


class Mutex:
    def __init__(self, name, security):
        attributes = Attributes(C.sizeof(Attributes),security.pointer,False)
        self.handle = check(k.CreateMutexW(C.byref(attributes),False,name))
        self.existing = C.get_last_error() == 183
        self.owned = False

    def acquire(self):
        """Nonblocking ownership, independent of other clients' open handles."""
        if self.owned:return True
        status=k.WaitForSingleObject(self.handle,0)
        if status in (0,128):
            self.owned=True
            return True
        if status==258:return False
        raise C.WinError(C.get_last_error())

    def close(self):
        try:
            if self.owned:check(k.ReleaseMutex(self.handle))
        finally:
            self.owned=False
            close(self.handle)
            self.handle = None


class Pipe:
    def __init__(self, handle):
        if handle == INVALID_HANDLE or not handle:
            raise C.WinError(C.get_last_error())
        self.handle = handle

    @classmethod
    def server(cls, name, security, *, first=False):
        attributes = Attributes(C.sizeof(Attributes),security.pointer,False)
        # Message framing + local clients only + explicit current-user DACL.
        access = 3 | 0x40000000 | (0x80000 if first else 0)
        return cls(k.CreateNamedPipeW(name,access,4|2|8,1,65536,4097,1000,C.byref(attributes)))

    @classmethod
    def client(cls, name, timeout=3):
        deadline=time.monotonic()+timeout
        while True:
            ready=k.WaitNamedPipeW(name,max(1,int((deadline-time.monotonic())*1000)))
            if ready:
                handle=k.CreateFileW(name,0xC0000000,0,None,3,0x40000000,None)
                if handle!=INVALID_HANDLE:break
            error=C.get_last_error()
            if error not in (2,231) or time.monotonic()>=deadline:raise C.WinError(error)
            time.sleep(min(.02,max(0,deadline-time.monotonic())))
        pipe = cls(handle)
        mode = W.DWORD(2)
        try:check(k.SetNamedPipeHandleState(pipe.handle,C.byref(mode),None,None))
        except BaseException:
            pipe.close()
            raise
        return pipe

    def _operation(self, function, *args, timeout=3):
        overlap = Overlapped()
        overlap.event = check(k.CreateEventW(None,True,False,None))
        count = W.DWORD()
        try:
            ok = function(self.handle,*args,C.byref(count),C.byref(overlap))
            error = C.get_last_error() if not ok else 0
            if error == 997:
                if k.WaitForSingleObject(overlap.event,int(timeout*1000)) == 258:
                    k.CancelIoEx(self.handle,C.byref(overlap))
                    k.GetOverlappedResult(self.handle,C.byref(overlap),C.byref(count),True)
                    raise TimeoutError("local pipe I/O timeout")
                ok = k.GetOverlappedResult(self.handle,C.byref(overlap),C.byref(count),False)
                error = C.get_last_error() if not ok else 0
            if error not in (0,234):
                raise C.WinError(error)
            return count.value,error == 234
        finally:
            close(overlap.event)

    def connect(self, timeout=0.25):
        overlap = Overlapped()
        overlap.event = check(k.CreateEventW(None,True,False,None))
        try:
            ok = k.ConnectNamedPipe(self.handle,C.byref(overlap))
            error = C.get_last_error() if not ok else 0
            if error == 535:return True
            if error == 997:
                if k.WaitForSingleObject(overlap.event,int(timeout*1000)) == 258:
                    k.CancelIoEx(self.handle,C.byref(overlap))
                    count = W.DWORD()
                    k.GetOverlappedResult(self.handle,C.byref(overlap),C.byref(count),True)
                    return False
                count = W.DWORD()
                check(k.GetOverlappedResult(self.handle,C.byref(overlap),C.byref(count),False))
                return True
            check(ok)
            return True
        finally:close(overlap.event)

    def read(self, limit=4096, timeout=3):
        buffer = C.create_string_buffer(limit+1)
        count,more = self._operation(k.ReadFile,buffer,limit+1,timeout=timeout)
        if more or count > limit:
            raise ValueError("pipe message exceeds limit")
        return buffer.raw[:count]

    def write(self, payload, timeout=3):
        buffer = C.create_string_buffer(payload)
        count,_ = self._operation(k.WriteFile,buffer,len(payload),timeout=timeout)
        if count != len(payload):
            raise OSError("incomplete pipe write")

    def server_pid(self):
        pid = W.ULONG()
        check(k.GetNamedPipeServerProcessId(self.handle,C.byref(pid)))
        return pid.value

    def close(self):
        close(self.handle)
        self.handle = None


# Read-only process metadata. The NT command-line class is capability checked
# dynamically; absent/changed APIs or malformed buffers cannot prove ownership.
class ProcessBasic(C.Structure):
    _fields_ = [("exit_status",W.LONG),("peb",C.c_void_p),("affinity",C.c_size_t),
                ("priority",W.LONG),("pid",C.c_size_t),("parent",C.c_size_t)]


class NativeUnicode(C.Structure):
    _fields_ = [("length",W.USHORT),("maximum",W.USHORT),("buffer",C.c_void_p)]


class ProcessEntry(C.Structure):
    _fields_ = [("size",W.DWORD),("usage",W.DWORD),("pid",W.DWORD),("heap",C.c_size_t),
                ("module",W.DWORD),("threads",W.DWORD),("parent",W.DWORD),
                ("priority",W.LONG),("flags",W.DWORD),("name",W.WCHAR*260)]


api(k,"CreateToolhelp32Snapshot",W.HANDLE,[W.DWORD,W.DWORD])
api(k,"Process32FirstW",W.BOOL,[W.HANDLE,C.POINTER(ProcessEntry)])
api(k,"Process32NextW",W.BOOL,[W.HANDLE,C.POINTER(ProcessEntry)])
try:
    native_dll = C.WinDLL("ntdll",use_last_error=True)
    native_query = api(native_dll,"NtQueryInformationProcess",W.LONG,
                       [W.HANDLE,C.c_int,C.c_void_p,W.ULONG,C.POINTER(W.ULONG)])
except (OSError,AttributeError):
    native_query = None


def process_entries():
    """Complete process snapshot; names/PIDs are hints, never ownership."""
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot==INVALID_HANDLE:raise C.WinError(C.get_last_error())
    entry=ProcessEntry();entry.size=C.sizeof(entry);rows=[]
    try:
        more=k.Process32FirstW(snapshot,C.byref(entry))
        if not more:raise C.WinError(C.get_last_error())
        while more:
            rows.append(dict(ProcessId=int(entry.pid),ParentProcessId=int(entry.parent),Name=entry.name))
            more=k.Process32NextW(snapshot,C.byref(entry))
        if C.get_last_error()!=18:raise C.WinError(C.get_last_error())
        return rows
    finally:close(snapshot)


def _created_from_handle(handle):
    values=[W.FILETIME() for _ in range(4)]
    check(k.GetProcessTimes(handle,*[C.byref(value) for value in values]))
    return ((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)/10_000_000-11644473600


def _sid_from_handle(handle):
    token=W.HANDLE();check(a.OpenProcessToken(handle,8,C.byref(token)))
    try:
        size=W.DWORD();a.GetTokenInformation(token,1,None,0,C.byref(size))
        if not 0<size.value<=65536:raise ValueError("invalid token metadata size")
        buffer=C.create_string_buffer(size.value)
        check(a.GetTokenInformation(token,1,buffer,size,C.byref(size)))
        pointer=C.cast(buffer,C.POINTER(C.c_void_p))[0];text=W.LPWSTR()
        check(a.ConvertSidToStringSidW(pointer,C.byref(text)))
        try:return text.value
        finally:k.LocalFree(text)
    finally:close(token)


def _native_command(handle):
    if native_query is None:raise OSError("native identity query unavailable")
    needed=W.ULONG()
    native_query(handle,60,None,0,C.byref(needed))
    if not C.sizeof(NativeUnicode)<=needed.value<=128*1024:
        raise OSError("native command-line length unavailable")
    buffer=C.create_string_buffer(needed.value);returned=W.ULONG()
    status=native_query(handle,60,buffer,len(buffer),C.byref(returned))
    if status<0 or not C.sizeof(NativeUnicode)<=returned.value<=len(buffer):raise OSError("native command-line query failed")
    value=NativeUnicode.from_buffer(buffer);lower=C.addressof(buffer);upper=lower+len(buffer)
    if (value.length%2 or value.length>value.maximum or value.buffer is None or
            not lower+C.sizeof(NativeUnicode)<=value.buffer<=value.buffer+value.length<=upper):
        raise ValueError("native command-line metadata bounds invalid")
    command=C.wstring_at(value.buffer,value.length//2)
    if not command or "\x00" in command:raise ValueError("native command-line empty or malformed")
    return command


def native_process_record(pid, *, handle=None):
    """All identity fields from one live held process, rechecked before return."""
    pid=int(pid);started=time.monotonic();owns=handle is None
    if owns:handle=check(k.OpenProcess(0x1000|0x100000,False,pid))
    try:
        if native_query is None:raise OSError("native identity query unavailable")
        if k.WaitForSingleObject(handle,0)!=258:raise ValueError("process is not live")
        created=_created_from_handle(handle);basic=ProcessBasic();returned=W.ULONG()
        status=native_query(handle,0,C.byref(basic),C.sizeof(basic),C.byref(returned))
        if status<0 or returned.value!=C.sizeof(basic) or basic.pid!=pid:
            raise OSError("native PID/parent identity unavailable")
        command=_native_command(handle)
        image=C.create_unicode_buffer(32768);size=W.DWORD(len(image))
        check(k.QueryFullProcessImageNameW(handle,0,image,C.byref(size)))
        sid=_sid_from_handle(handle)
        if (k.WaitForSingleObject(handle,0)!=258 or _created_from_handle(handle)!=created
                or time.monotonic()-started>8):
            raise ValueError("native process exited/changed or query budget exceeded")
        return dict(ProcessId=pid,ParentProcessId=int(basic.parent),Name=Path(image.value).name,
                    ExecutablePath=image.value,CommandLine=command,CreatedAt=created,UserSid=sid)
    finally:
        if owns:close(handle)


def native_process_observation(hint):
    """Partial read-only evidence from ONE held live process; no stop rights."""
    pid=int(hint['ProcessId'])
    row=dict(hint,ExecutablePath=None,CommandLine=None,CreatedAt=None,UserSid=None)
    handle=k.OpenProcess(0x1000|0x100000,False,pid)
    if not handle:return row  # access denied/invalid handle never proves exit
    try:
        status=k.WaitForSingleObject(handle,0)
        if status==0:return dict(row,ExitedConfirmed=True)
        if status!=258:return row
        try:birth=_created_from_handle(handle)
        except (OSError,ValueError):return row
        row['CreatedAt']=birth
        try:
            basic=ProcessBasic();returned=W.ULONG()
            if native_query is not None and native_query(handle,0,C.byref(basic),C.sizeof(basic),C.byref(returned))>=0 and returned.value==C.sizeof(basic) and basic.pid==pid:
                row['ParentProcessId']=int(basic.parent)
        except (OSError,ValueError):pass
        try:row['CommandLine']=_native_command(handle)
        except (OSError,ValueError):pass
        try:
            image=C.create_unicode_buffer(32768);size=W.DWORD(len(image))
            check(k.QueryFullProcessImageNameW(handle,0,image,C.byref(size)))
            row['ExecutablePath']=image.value
        except (OSError,ValueError):pass
        try:row['UserSid']=_sid_from_handle(handle)
        except (OSError,ValueError):pass
        status=k.WaitForSingleObject(handle,0)
        if status==0:return dict(row,ExitedConfirmed=True)
        if status!=258 or _created_from_handle(handle)!=birth:
            return dict(hint,ExecutablePath=None,CommandLine=None,CreatedAt=None,UserSid=None)
        return row
    except (OSError,ValueError):
        return dict(hint,ExecutablePath=None,CommandLine=None,CreatedAt=None,UserSid=None)
    finally:close(handle)
