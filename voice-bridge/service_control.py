"""Unified controller entry. No business code executes on import."""
import sys
sys.dont_write_bytecode=True
from service_control.launch import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # The installed VBS has no console. Record only a fixed error category
        # in the pre-created, explicitly protected local file; no broad fallback.
        from pathlib import Path
        import sys
        target=Path(__file__).resolve().parent/'logs/service-control/startup-error.txt'
        try:
            if '--fixture' not in sys.argv and target.is_file():
                from service_control.windows import Security,current_sid
                security=Security(current_sid())
                try:
                    security.secure_file(target)
                    target.write_text('Silent startup failed: manager initialization failed.\n',encoding='utf-8')
                    import os,time,uuid
                    from service_control.state import atomic_json
                    atomic_json(target.with_name('startup-error.json'),dict(at=time.time(),pid=os.getpid(),
                        error_seq=uuid.uuid4().hex,stage='entry_initialization',error_category=type(error).__name__),
                        secure=security.secure_file)
                finally:security.close()
        except (OSError,ValueError):pass
        print('Control initialization failed: '+type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
