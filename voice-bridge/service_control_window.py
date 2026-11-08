"""Human-facing entry; show Tk before any dependency/process check."""
import sys
sys.dont_write_bytecode=True

if __name__ == "__main__":
    try:
        from service_control.launch import main,parser
        # This entry is exclusively the foreground window; forwarded fixture
        # arguments cannot select a core/service or a non-GUI command.
        options=parser().parse_args(sys.argv[1:])
        if options.core or options.service or options.owner or options.check_once or options.command!='ensure':
            raise ValueError('invalid foreground window arguments')
        raise SystemExit(main(["--window",*sys.argv[1:]]))
    except Exception as error:
        # Importing tkinter does not prove Tcl can create a window. Native
        # feedback remains visible even if the GUI runtime fails immediately.
        import ctypes
        # Python 3.11 __file__ comes from the fixed absolute GUI launch path.
        # Keep this failure handler independent of filesystem/path resolution.
        entry_path=globals().get("__file__") or (sys.argv[0] if sys.argv else "")
        separator=max(entry_path.rfind("\\"),entry_path.rfind("/"))
        voice_path=entry_path[:separator]
        project_pythonw=voice_path+"\\venv\\Scripts\\pythonw.exe"
        readme_path=voice_path+"\\README.md"
        message=('无法显示语音服务状态窗口。\nTk/GUI依赖或控制入口无法初始化。\n原因类型：'+type(error).__name__+
                 '\n实际解释器：'+sys.executable+'\n项目解释器：'+str(project_pythonw)+
                 '\n入口：'+str(entry_path)+'\n请查看项目排查说明：'+str(readme_path))
        ctypes.windll.user32.MessageBoxW(None,message,'语音服务启动失败',0x10)
        raise SystemExit(1)
