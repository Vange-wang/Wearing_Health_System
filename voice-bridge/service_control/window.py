"""Tk renders immediately; bounded IPC/CIM work stays on background threads."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import time
from .launch import connect_or_start, verified_control, PYTHONW, PROJECT, parser, control_paths
from .identity import invocation
from .windows import Security, Mutex, process_created, current_sid, api, u

api(u,"IsWindow",W.BOOL,[W.HWND])
api(u,"GetAncestor",W.HWND,[W.HWND,W.UINT])
api(u,"GetWindowThreadProcessId",W.DWORD,[W.HWND,C.POINTER(W.DWORD)])
api(u,"ShowWindow",W.BOOL,[W.HWND,C.c_int])
api(u,"SetForegroundWindow",W.BOOL,[W.HWND])
class FlashInfo(C.Structure):
    _fields_=[("size",W.UINT),("hwnd",W.HWND),("flags",W.DWORD),("count",W.UINT),("timeout",W.DWORD)]
api(u,"FlashWindowEx",W.BOOL,[C.POINTER(FlashInfo)])

LABELS={"voice":"本机语音","discovery":"LAN / mDNS","udp_discovery":"PC 配对发现","box_link":"BOX 连接回执","hermes":"Hermes 工具依赖",
        "deepseek":"DeepSeek 轻量通道","data":"本地健康数据直答","memory_read":"本地记忆读取",
        "memory":"记忆写删访问","mdns":"mDNS 进程","memory_service":"记忆进程"}
COLOURS={"READY":"#137a44","DEGRADED":"#9b6200","WAIT_NETWORK":"#9b6200",
         "FAILED":"#b62929","CONFLICT":"#b62929","UNKNOWN":"#626975","STOPPED":"#626975",
         "CHECKING":"#2458a6","STARTING":"#2458a6"}


def restore_window(paths):
    from .processes import verify_peer
    saved=json.loads(paths.gui.read_text(encoding="utf-8"))
    if saved.get("project_root")!=str(paths.project.resolve()) or saved.get("user_sid")!=paths.sid:
        raise ValueError("window project/user mismatch")
    pid, hwnd=saved["pid"],saved["hwnd"]
    if type(pid) is not int or type(hwnd) is not int or not u.IsWindow(hwnd):raise ValueError("stale window")
    actual=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(actual))
    if actual.value!=pid or process_created(pid)!=saved["created_at"]:raise ValueError("window PID changed")
    record=verify_peer(pid,paths,PROJECT/"voice-bridge/service_control_window.py",PYTHONW)
    peer=control_paths(parser().parse_args(["--window",*invocation(record)[2]]))
    if peer.scope!=paths.scope or peer.state_dir!=paths.state_dir:raise ValueError("window scope changed")
    u.ShowWindow(hwnd,9)
    foreground=bool(u.SetForegroundWindow(hwnd))
    if not foreground:
        info=FlashInfo(C.sizeof(FlashInfo),hwnd,3,3,0);u.FlashWindowEx(C.byref(info))
    return dict(pid=pid,hwnd=hwnd,foreground=foreground,created_at=record["CreatedAt"])


class ControlWindow:
    def __init__(self,paths,options, *, security=None,window_mutex=None):
        global tk,ttk,messagebox,queue,threading,SnapshotReader,atomic_json
        import tkinter as tk
        from tkinter import ttk,messagebox
        self.paths,self.options=paths,options
        self.started=time.monotonic()
        self.security=security or Security(paths.sid)
        self.window_mutex=window_mutex or Mutex("Local\\voice-control-window-"+paths.scope,self.security)
        if window_mutex is None:self.window_mutex.acquire()
        self.closed=False;self.gui_published=False;self.gui_error=None
        self.root=tk.Tk()
        self.root.title("语音服务状态"+(" · 隔离验证 "+paths.namespace if options.fixture else ""))
        self.root.geometry("860x690");self.root.minsize(760,560)
        self.root.configure(background="#f4f6fa")
        initial=tk.Label(self.root,text="正在检查语音服务",background="#f4f6fa",font=("Microsoft YaHei",16))
        initial.pack(anchor="w",padx=22,pady=22)
        self.root.deiconify();self.root.update()
        self.visible_ms=round((time.monotonic()-self.started)*1000,2)
        self.first_visible_at=time.time()
        # The real HWND already exists and has been painted. Publish its exact
        # locator before assembling the remaining labels; repeated entries can
        # verify/restore this window without waiting for widget construction.
        try:
            if self.window_mutex.owned:self.publish_window()
        except (OSError,ValueError) as error:self.gui_error=type(error).__name__
        import queue,threading
        from .state import SnapshotReader,atomic_json
        self.queue=queue.Queue();self.closed=False
        self.reader=SnapshotReader(paths.project,paths.sid)
        self.communication_error=None;self.latest={};self.connected=False;self.busy=False
        self.last_verified=0
        style=ttk.Style();style.theme_use("clam")
        style.configure("TFrame",background="#f4f6fa")
        style.configure("TLabel",background="#f4f6fa",font=("Microsoft YaHei",10))
        container=ttk.Frame(self.root,padding=22);container.pack(fill="both",expand=True)
        initial.destroy()
        self.title=ttk.Label(container,text="正在检查语音服务",font=("Microsoft YaHei",18,"bold"))
        self.title.pack(anchor="w")
        self.progress=ttk.Label(container,text="窗口已打开，后台正在连接管理器",wraplength=800)
        self.progress.pack(anchor="w",pady=(8,14))
        self.rows={}
        for name in LABELS:
            frame=ttk.Frame(container);frame.pack(fill="x",pady=4)
            ttk.Label(frame,text=LABELS[name],width=20).pack(side="left",anchor="n")
            label=ttk.Label(frame,text="CHECKING · 等待检查",wraplength=570)
            label.pack(side="left",fill="x",expand=True);self.rows[name]=label
        self.tts=ttk.Label(container,text="TTS：尚未取得有效探测",wraplength=800)
        self.tts.pack(anchor="w",pady=(12,4))
        self.checked=ttk.Label(container,text="最后检查：未完成")
        self.checked.pack(anchor="w")
        self.footer=ttk.Label(container,text="关闭窗口只关闭显示；管理器与服务继续运行。下次登录会按自启配置启动。",wraplength=800)
        self.footer.pack(anchor="w",pady=(12,8))
        self.startup_failure=None
        try:
            with (paths.state_dir/'startup-error.txt').open(encoding='utf-8') as source:error=source.read(256).strip()
            messages={'Silent startup failed: Python or entry script is missing.':'上次静默启动失败：Python或入口脚本缺失。',
                      'Silent startup failed: unable to launch the unified manager.':'上次静默启动失败：统一管理器无法启动。',
                      'Silent startup failed: manager initialization failed.':'上次静默启动失败：管理器初始化未完成。'}
            if error in messages and 0<=time.time()-(paths.state_dir/'startup-error.txt').stat().st_mtime<=120:
                self.startup_failure=messages[error]
                ttk.Label(container,text=messages[error]+" 当前就绪以本轮检查为准。",foreground=COLOURS['FAILED']).pack(anchor='w')
        except (OSError,ValueError):pass
        if options.fixture:
            ttk.Label(container,text="隔离验证：使用独立假服务，不能代表当前运行服务、设备或外部模型已验收。").pack(anchor="w")
        buttons=ttk.Frame(container);buttons.pack(fill="x",pady=(12,0))
        ttk.Button(buttons,text="重新检查 / 安全重试",command=lambda:self.action("retry")).pack(side="left",padx=(0,8))
        ttk.Button(buttons,text="打开日志",command=self.open_logs).pack(side="left",padx=(0,8))
        ttk.Button(buttons,text="选择网卡",command=self.choose_adapter).pack(side="left",padx=(0,8))
        ttk.Button(buttons,text="停止本管理器启动的服务",command=self.stop_services).pack(side="left")
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        self.root.update_idletasks();self.root.deiconify();self.root.update()
        if self.gui_error is None:
            self.root.after(0,self.start)
        else:
            self.communication_error="状态/日志目录不可写或ACL失败："+self.gui_error
            self.title.configure(text="FAILED · 无法保存控制状态",foreground=COLOURS["FAILED"])
            self.progress.configure(text=self.communication_error)
        self.root.after(250,self.poll)
        self.root.after(1000,self.refresh)
        if options.fixture_window_lifetime is not None:
            self.root.after(int(options.fixture_window_lifetime*1000),self.close)

    def background(self,function):
        def work():
            try:self.queue.put(("ok",function()))
            except Exception as error:self.queue.put(("error",type(error).__name__))
        threading.Thread(target=work,daemon=True).start()

    def start(self):
        try:self._start()
        except (OSError,ValueError) as error:
            self.communication_error="状态/日志目录不可写或ACL失败："+type(error).__name__
            self.title.configure(text="FAILED · 无法保存控制状态",foreground=COLOURS["FAILED"])
            self.progress.configure(text=self.communication_error)

    def _start(self):
        if not self.window_mutex.owned:
            self.progress.configure(text="正在恢复已有状态窗口")
            def restore():
                if not getattr(self.options,'intent_dispatched',False):connect_or_start(self.paths,self.options)
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:
                        restored=restore_window(self.paths)
                        return {"restored":restored}
                    except (OSError,ValueError,KeyError):time.sleep(.1)
                raise ValueError("已有窗口身份或句柄不可核验，保留现场")
            self.background(restore);return
        if not self.gui_published:self.publish_window()
        self.background(lambda:verified_control(self.paths,'status',fixture=self.options.fixture)
                        if getattr(self.options,'intent_dispatched',False) else connect_or_start(self.paths,self.options))

    def publish_window(self):
        from .state import atomic_json
        self.paths.state_dir.mkdir(parents=True,exist_ok=True)
        self.security.secure_file(self.paths.state_dir)
        hwnd=int(u.GetAncestor(self.root.winfo_id(),2))
        atomic_json(self.paths.gui,dict(schema_version=1,pid=os.getpid(),created_at=process_created(os.getpid()),
                    hwnd=hwnd,project_root=str(self.paths.project.resolve()),user_sid=self.paths.sid,
                    visible_ms=self.visible_ms,first_visible_at=self.first_visible_at),secure=self.security.secure_file)
        self.gui_published=True

    def poll(self):
        while not self.queue.empty():
            kind,value=self.queue.get_nowait()
            if kind=="error":
                self.communication_error="管理器存在但不可通信 / 身份未核验："+value
                self.title.configure(text="UNKNOWN · 管理器连接未完成",foreground=COLOURS["UNKNOWN"])
                self.progress.configure(text=self.communication_error)
            elif "restored" in value:
                self.close();return
            elif value.get("stop_prompt"):
                entries=[e for e in value.get("stop_candidates",[]) if e.get("verified") is True]
                if not entries:
                    messagebox.showinfo("没有可停止的对象","未发现已核验created服务；复用及共享服务保留。",parent=self.root)
                    continue
                listing="\n".join(f"{e['name']} · PID {e['pid']}" for e in entries)
                if messagebox.askyesno("确认停止",listing+"\n\n仅停止这些对象，并关闭自动恢复。",parent=self.root):
                    preview_id=value["stop_preview_id"]
                    self.background(lambda preview_id=preview_id:verified_control(self.paths,"stop",fixture=self.options.fixture,request_id=preview_id))
            elif value.get("accepted"):
                self.communication_error=None;self.connected=True
                self.last_verified=time.monotonic()
                self.reader.verify_identity(value["identity"])
                self.refresh(schedule=False)
            else:
                self.progress.configure(text=value.get("reason","请求未接受"))
        if not self.closed:self.root.after(250,self.poll)

    def refresh(self, *, schedule=True):
        if self.closed:return
        try:
            self._refresh()
        finally:
            # Input/transport failures must not cancel future observations.
            # Programming errors still propagate; no blanket success fallback.
            if schedule and not self.closed:self.root.after(1000,self.refresh)

    def _refresh(self):
        if self.connected:
            identity=self.reader.identity
            if identity is None or process_created(identity["core_pid"])!=identity["core_created_at"]:
                self.communication_error="管理器身份已改变；等待重新核验"
                self.connected=False
                self.background(lambda:verified_control(self.paths,"status",fixture=self.options.fixture))
            try:
                state=self.reader.read(self.paths.snapshot)
            except (OSError,ValueError,TypeError,OverflowError,KeyError,RecursionError) as error:
                state={"overall":"UNKNOWN","reason":"快照输入不可验证："+type(error).__name__,"components":{},"valid":False}
            if self.communication_error:state={"overall":"UNKNOWN","reason":self.communication_error,"components":{}}
            self.latest=state
            status=state["overall"]
            self.title.configure(text=status+" · 语音服务状态",foreground=COLOURS.get(status,COLOURS["UNKNOWN"]))
            elapsed=state.get("round_elapsed_s",0)
            self.progress.configure(text=f"{state.get('phase',state.get('reason','检查中'))} · 已用 {elapsed:.1f} 秒\n{state.get('reason','')}")
            for name,label in self.rows.items():
                value=state.get("components",{}).get(name,{"state":"UNKNOWN","reason":"未取得有效检查"})
                label.configure(text=f"{value['state']} · {value.get('reason','')}",foreground=COLOURS.get(value["state"],COLOURS["UNKNOWN"]))
            voice=state.get("components",{}).get("voice",{})
            tts=voice.get("tts")
            self.tts.configure(text=("TTS：配置 {configured_primary} / 实际 {active_engine} / 最近探测 {last_probe_ok} / 时间 {last_probe_ts}".format(**tts)
                                     if tts else "TTS：尚未取得有效探测"))
            checked=voice.get("last_check_at")
            self.checked.configure(text="最后检查："+(time.strftime("%H:%M:%S",time.localtime(checked)) if checked else "未知"))
            if self.options.fixture:
                atomic_json(self.paths.state_dir/"fixture-view.json",
                            dict(overall=status,title=self.title.cget("text"),progress=self.progress.cget("text"),
                                 startup_failure=self.startup_failure,
                                 tts=self.tts.cget('text'),
                                 rows={name:label.cget("text") for name,label in self.rows.items()},
                                 displayed_at=time.time()),secure=self.security.secure_file)
            if time.monotonic()-self.last_verified>=60:
                self.last_verified=time.monotonic()
                self.background(lambda:verified_control(self.paths,"status",fixture=self.options.fixture))
        elif not self.communication_error:
            self.progress.configure(text=f"正在连接管理器 · 已用 {time.monotonic()-self.started:.1f} 秒")
        # Leave scheduling/rendering margin inside the <=2s display contract.
        # This observer runs only in Tk; voice requests never await it.

    def action(self,command):
        self.progress.configure(text="正在发送安全检查请求")
        self.background(lambda:verified_control(self.paths,command,fixture=self.options.fixture))

    def stop_services(self):
        self.progress.configure(text="正在核对具体停止对象")
        self.background(lambda:dict(verified_control(self.paths,"status",fixture=self.options.fixture),stop_prompt=True))

    def choose_adapter(self):
        candidates=self.latest.get("components",{}).get("discovery",{}).get("candidates",[])
        if not candidates:
            messagebox.showinfo("选择网卡","当前没有有效物理LAN候选，请先连接设备所在网络。",parent=self.root);return
        dialog=tk.Toplevel(self.root);dialog.title("选择设备所在网卡")
        def choose(item):
            atomic_json(self.paths.settings,{"interface_index":item["index"]},secure=self.security.secure_file)
            dialog.destroy();self.action("retry")
        for item in candidates:
            ttk.Button(dialog,text=f"{item['name']} · {item['address']}",command=lambda item=item:choose(item)).pack(fill="x",padx=16,pady=8)

    def open_logs(self):
        self.paths.state_dir.mkdir(parents=True,exist_ok=True)
        os.startfile(str(self.paths.state_dir))

    def close(self):
        if self.closed:return
        self.closed=True
        if hasattr(self,"window_mutex"):self.window_mutex.close()
        if hasattr(self,"security"):self.security.close()
        self.root.destroy()  # intentionally no stop/ensure/recovery request


def show(paths,options):
    security=Security(paths.sid)
    mutex=None;window=None
    try:
        mutex=Mutex("Local\\voice-control-window-"+paths.scope,security)
        if not mutex.acquire():
            # Repeated entries do not each construct a Tk window or retain an
            # ownership lease. Restore only the fully verified existing HWND.
            deadline=time.monotonic()+8
            while True:
                try:
                    restore_window(paths)
                    connect_or_start(paths,options)
                    return 0
                except (OSError,ValueError,KeyError):
                    if time.monotonic()>=deadline:raise
                    time.sleep(.05)
        window=ControlWindow(paths,options,security=security,window_mutex=mutex)
        window.root.mainloop()
        return 0
    finally:
        if window is not None:window.close()
        else:
            if mutex is not None:mutex.close()
            security.close()
