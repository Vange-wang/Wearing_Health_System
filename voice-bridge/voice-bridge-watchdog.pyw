"""Silent watchdog for voice-bridge, mDNS, and memory_server on Windows."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


VOICE_BRIDGE_DIR = Path(r"D:\workbuddy_project\项目\可穿戴健康辅助系统\voice-bridge")
LOG_DIR = VOICE_BRIDGE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

HERMES_SCRIPTS = Path(r"C:\Users\86166\.hermes\scripts")
HERMES_LOGS = Path(r"C:\Users\86166\.hermes\logs")
HERMES_LOGS.mkdir(parents=True, exist_ok=True)

PYTHON_VENV = VOICE_BRIDGE_DIR / "venv" / "Scripts" / "python.exe"
PYTHON_CONDA = Path(r"D:\miniconda\python.exe")
VOICE_SCRIPT = VOICE_BRIDGE_DIR / "run.py"
MDNS_SCRIPT = VOICE_BRIDGE_DIR / "mdns_advertise.py"
MEMORY_SCRIPT = HERMES_SCRIPTS / "memory_server.py"

MDNS_PID_FILE = LOG_DIR / "mdns.pid"
CHECK_INTERVAL = 60
COOLDOWN = 30
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUPS = 3
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def create_rotating_logger(
    name: str, path: Path, *, max_bytes: int = LOG_MAX_BYTES, backups: int = LOG_BACKUPS
) -> logging.Logger:
    """Create one bounded UTF-8 file logger, replacing stale handlers on reload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


log = create_rotating_logger("voice-bridge.watchdog", LOG_DIR / "watchdog.log")
mdns_owner_log = create_rotating_logger(
    "voice-bridge.watchdog.mdns-owner", LOG_DIR / "mdns-owner.log"
)


def _normal_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _command_args(command_line: str | None) -> list[str]:
    if not command_line:
        return []
    return [quoted or bare for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', command_line)]


def _record_matches(record: dict, script_path: Path, executable_path: Path) -> bool:
    args = _command_args(record.get("CommandLine"))
    if len(args) < 2:
        return False
    actual_executable = record.get("ExecutablePath") or args[0]
    if _normal_path(actual_executable) != _normal_path(executable_path):
        return False
    expected_script = _normal_path(script_path)
    return any(_normal_path(arg) == expected_script for arg in args[1:])


def process_records_match(
    records: list[dict], script_path: Path, executable_path: Path
) -> bool:
    """Match an exact executable+script command, never a tasklist name substring."""
    return any(_record_matches(record, script_path, executable_path) for record in records)


def verified_pid_record(
    pid_text: str, record: dict, script_path: Path, executable_path: Path
) -> bool:
    try:
        expected_pid = int(pid_text.strip())
        actual_pid = int(record.get("ProcessId"))
    except (TypeError, ValueError):
        return False
    return expected_pid == actual_pid and _record_matches(
        record, script_path, executable_path
    )


def _query_process_records(pid: int | None = None) -> list[dict]:
    """Read CIM process metadata as JSON without logging command lines."""
    filter_clause = f" -Filter 'ProcessId = {int(pid)}'" if pid is not None else ""
    command = (
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
        f"Get-CimInstance Win32_Process{filter_clause} | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["pwsh.exe", "-NoLogo", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        payload = json.loads(result.stdout)
        return payload if isinstance(payload, list) else [payload]
    except Exception:
        return []


def _read_pid(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip()
    except Exception:
        return None


def _write_pid(path: Path, pid: int) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(str(pid), encoding="ascii")
    temp.replace(path)


def is_script_running(
    script_path: Path, pid_file: Path, executable_path: Path = PYTHON_VENV
) -> bool:
    """Verify a PID file first, then exact CIM command lines; refresh ownership PID."""
    pid_text = _read_pid(pid_file)
    if pid_text and pid_text.isdecimal():
        records = _query_process_records(int(pid_text))
        if records and verified_pid_record(
            pid_text, records[0], script_path, executable_path
        ):
            return True
        pid_file.unlink(missing_ok=True)

    for record in _query_process_records():
        if _record_matches(record, script_path, executable_path):
            try:
                _write_pid(pid_file, int(record["ProcessId"]))
            except Exception:
                pass
            return True
    return False


def is_port_listening(port: int) -> bool:
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        local_port = re.compile(rf"^\s*TCP\s+\S*:{int(port)}\s+\S+\s+LISTENING\s+\d+\s*$")
        return any(local_port.match(line) for line in result.stdout.splitlines())
    except Exception:
        return False


def _spawn_logged(
    args: list[Path | str], *, cwd: Path, output_path: Path,
    pid_file: Path | None = None, env: dict | None = None,
) -> int:
    """Launch with an argument list; no shell interpolation or cross-shell quoting."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("ab", buffering=0) as output:
        process = subprocess.Popen(
            [os.fspath(arg) for arg in args],
            cwd=os.fspath(cwd),
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
    if pid_file is not None:
        _write_pid(pid_file, process.pid)
    return process.pid


_last_start = {"voice_bridge": 0.0, "mdns": 0.0, "memory_server": 0.0}


def _in_cooldown(name: str) -> bool:
    return (time.time() - _last_start[name]) < COOLDOWN


def start_voice_bridge() -> None:
    _last_start["voice_bridge"] = time.time()
    pid = _spawn_logged(
        [PYTHON_VENV, VOICE_SCRIPT], cwd=VOICE_BRIDGE_DIR,
        output_path=LOG_DIR / "voice-bridge.log",
    )
    log.info("启动 voice-bridge pid=%d", pid)


def start_mdns() -> None:
    _last_start["mdns"] = time.time()
    pid = _spawn_logged(
        [PYTHON_VENV, MDNS_SCRIPT], cwd=VOICE_BRIDGE_DIR,
        output_path=LOG_DIR / "mdns.log", pid_file=MDNS_PID_FILE,
    )
    log.info("启动 mDNS pid=%d", pid)
    mdns_owner_log.info("owner=start pid=%d script=%s", pid, MDNS_SCRIPT.name)


def start_memory_server() -> None:
    _last_start["memory_server"] = time.time()
    env = os.environ.copy()
    env["HERMES_HOME"] = os.fspath(Path.home() / ".hermes")
    pid = _spawn_logged(
        [PYTHON_CONDA, MEMORY_SCRIPT], cwd=HERMES_SCRIPTS,
        output_path=HERMES_LOGS / "memory_server.log", env=env,
    )
    log.info("启动 memory_server pid=%d", pid)


def check_and_restart() -> None:
    if not is_port_listening(8710):
        if _in_cooldown("voice_bridge"):
            log.info("voice-bridge 8710 未监听，但冷却中")
        else:
            log.warning("voice-bridge 8710 未监听，重启")
            start_voice_bridge()

    if not is_script_running(MDNS_SCRIPT, MDNS_PID_FILE, PYTHON_VENV):
        if _in_cooldown("mdns"):
            log.info("mDNS 未运行，但冷却中")
        else:
            log.warning("mDNS 未运行，重启")
            mdns_owner_log.warning("owner=missing action=restart")
            start_mdns()

    if not is_port_listening(8781):
        if _in_cooldown("memory_server"):
            log.info("memory_server 8781 未监听，但冷却中")
        else:
            log.warning("memory_server 8781 未监听，重启")
            start_memory_server()


def main(check_once: bool = False) -> None:
    log.info("watchdog 启动，检查间隔=%ds check_once=%s", CHECK_INTERVAL, check_once)
    if check_once:
        check_and_restart()
        return
    time.sleep(10)
    check_and_restart()
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            check_and_restart()
        except Exception:
            log.exception("检测异常")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-once", action="store_true")
    args = parser.parse_args()
    main(check_once=args.check_once)
