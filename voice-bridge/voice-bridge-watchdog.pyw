"""voice-bridge 守护进程（后台静默运行）。

每 60 秒检测 voice-bridge(8710)、mDNS、memory_server(8781) 是否存活，
挂了自动拉起。放在 Windows 启动文件夹即可开机自启。

- 无窗口运行（.pyw 扩展名，不会弹黑框）
- 日志写 logs/watchdog.log（定期截断，防无限增长）
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# --- 路径 ---
VOICE_BRIDGE_DIR = Path(r"D:\workbuddy_project\项目\可穿戴健康辅助系统\voice-bridge")
LOG_DIR = VOICE_BRIDGE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

HERMES_SCRIPTS = Path(r"C:\Users\86166\.hermes\scripts")
HERMES_LOGS = Path(r"C:\Users\86166\.hermes\logs")
HERMES_LOGS.mkdir(parents=True, exist_ok=True)

PYTHON_VENV = VOICE_BRIDGE_DIR / "venv" / "Scripts" / "python.exe"
PYTHON_CONDA = Path(r"D:\miniconda\python.exe")

CHECK_INTERVAL = 60  # 秒
LOG_MAX_BYTES = 512 * 1024  # 512KB 后截断
COOLDOWN = 30  # 启动后冷却时间（秒），防止服务还没起来就被重复拉起

# --- 日志 ---
log_file = LOG_DIR / "watchdog.log"
if log_file.exists() and log_file.stat().st_size > LOG_MAX_BYTES:
    log_file.write_text("")  # 截断

logging.basicConfig(
    filename=str(log_file),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("watchdog")


def is_port_listening(port: int) -> bool:
    """检查端口是否有进程在监听。"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, timeout=5, creationflags=0x08000000,
        )
        output = result.stdout.decode("gbk", errors="replace")
        for line in output.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                return True
    except Exception:
        pass
    return False


def is_process_running(name_pattern: str) -> bool:
    """检查是否有匹配名称的进程在运行。"""
    try:
        result = subprocess.run(
            ["tasklist"],
            capture_output=True, timeout=5, creationflags=0x08000000,
        )
        output = result.stdout.decode("gbk", errors="replace")
        return name_pattern.lower() in output.lower()
    except Exception:
        return False


# 启动时间戳（防止重复拉起）
_last_start = {"voice_bridge": 0, "mdns": 0, "memory_server": 0}


def _in_cooldown(name: str) -> bool:
    """判断某服务是否还在冷却期内。"""
    return (time.time() - _last_start[name]) < COOLDOWN


def start_voice_bridge():
    """启动 voice-bridge（端口 8710）。"""
    log.info("启动 voice-bridge...")
    _last_start["voice_bridge"] = time.time()
    subprocess.Popen(
        f'cmd /c "cd /d {VOICE_BRIDGE_DIR} && {PYTHON_VENV} run.py >> logs\\voice-bridge.log 2>&1"',
        shell=True,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )


def start_mdns():
    """启动 mDNS 广播。"""
    log.info("启动 mDNS...")
    _last_start["mdns"] = time.time()
    subprocess.Popen(
        f'cmd /c "cd /d {VOICE_BRIDGE_DIR} && {PYTHON_VENV} mdns_advertise.py >> logs\\mdns.log 2>&1"',
        shell=True,
        creationflags=0x08000000,
    )


def start_memory_server():
    """启动 memory_server（端口 8781）。"""
    log.info("启动 memory_server...")
    _last_start["memory_server"] = time.time()
    env = os.environ.copy()
    env["HERMES_HOME"] = str(Path.home() / ".hermes")
    subprocess.Popen(
        f'cmd /c "{PYTHON_CONDA} {HERMES_SCRIPTS / "memory_server.py"} >> {HERMES_LOGS / "memory_server.log"} 2>&1"',
        shell=True,
        env=env,
        creationflags=0x08000000,
    )


def check_and_restart():
    """检测并重启挂掉的服务（带冷却）。"""
    # voice-bridge (8710)
    if not is_port_listening(8710):
        if _in_cooldown("voice_bridge"):
            log.info("voice-bridge 8710 未监听，但冷却中，跳过")
        else:
            log.warning("voice-bridge 8710 未监听，重启")
            start_voice_bridge()

    # mDNS（检查 python 进程中有无 mdns_advertise）
    if not is_process_running("mdns_advertise"):
        if _in_cooldown("mdns"):
            log.info("mDNS 未运行，但冷却中，跳过")
        else:
            log.warning("mDNS 未运行，重启")
            start_mdns()

    # memory_server (8781)
    if not is_port_listening(8781):
        if _in_cooldown("memory_server"):
            log.info("memory_server 8781 未监听，但冷却中，跳过")
        else:
            log.warning("memory_server 8781 未监听，重启")
            start_memory_server()


def main():
    log.info("watchdog 启动，每 %ds 检测一次", CHECK_INTERVAL)
    # 启动时先做一次完整检测
    time.sleep(10)  # 等系统启动稳定
    check_and_restart()

    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            check_and_restart()
        except Exception as e:
            log.error("检测异常: %s", e)


if __name__ == "__main__":
    main()
