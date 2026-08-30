import importlib.util
from importlib.machinery import SourceFileLoader
from logging.handlers import RotatingFileHandler
from pathlib import Path


WATCHDOG_PATH = Path(__file__).resolve().parent.parent / "voice-bridge-watchdog.pyw"


def _load_watchdog():
    loader = SourceFileLoader("voice_bridge_watchdog_test", str(WATCHDOG_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_mdns_match_requires_verified_command_line_and_executable():
    watchdog = _load_watchdog()
    script = Path(r"D:\project with spaces\mdns_advertise.py")
    python = Path(r"D:\project with spaces\venv\Scripts\python.exe")

    tasklist_only = [{"ProcessId": 10, "Name": "python.exe", "CommandLine": None}]
    verified_cim = [{
        "ProcessId": 11,
        "ExecutablePath": str(python),
        "CommandLine": f'"{python}" "{script}"',
    }]
    wrong_script = [{
        "ProcessId": 12,
        "ExecutablePath": str(python),
        "CommandLine": f'"{python}" "D:\\other\\mdns_advertise.py.bak"',
    }]

    assert not watchdog.process_records_match(tasklist_only, script, python)
    assert watchdog.process_records_match(verified_cim, script, python)
    assert not watchdog.process_records_match(wrong_script, script, python)


def test_verified_pid_must_match_record_pid_command_and_executable():
    watchdog = _load_watchdog()
    script = Path(r"D:\voice\mdns_advertise.py")
    python = Path(r"D:\voice\venv\Scripts\python.exe")
    record = {
        "ProcessId": 321,
        "ExecutablePath": str(python),
        "CommandLine": f'"{python}" "{script}"',
    }

    assert watchdog.verified_pid_record("321", record, script, python)
    assert not watchdog.verified_pid_record("999", record, script, python)


def test_rotating_logger_has_fixed_limits(tmp_path):
    watchdog = _load_watchdog()
    logger = watchdog.create_rotating_logger(
        "watchdog-test", tmp_path / "owner.log", max_bytes=128, backups=2
    )
    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 128
    assert handlers[0].backupCount == 2


def test_repeated_checks_do_not_launch_duplicate_mdns(monkeypatch):
    watchdog = _load_watchdog()
    starts = []
    monkeypatch.setattr(watchdog, "is_port_listening", lambda port: True)
    monkeypatch.setattr(watchdog, "is_script_running", lambda *args: True)
    monkeypatch.setattr(watchdog, "start_mdns", lambda: starts.append(True))

    watchdog.check_and_restart()
    watchdog.check_and_restart()

    assert starts == []
