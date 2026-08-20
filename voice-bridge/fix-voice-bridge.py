# -*- coding: utf-8 -*-
"""voice-bridge 自助诊断修复工具（用户版，替代脆弱 bat）。

用途：BOX-3 屏幕显示「闭嘴/黑脸」、语音没反应时，双击本脚本自动诊断 + 修复。

用法：
  - 双击（或命令行）：venv\\Scripts\\python.exe fix-voice-bridge.py
  - 它会：① 检查服务健康 ② 发现异常则杀净残留进程并重启 ③ 输出清晰下一步

设计要点（相比 bat 更可靠）：
  - 用 psutil/wmic 精确匹配命令行杀进程，避免误杀/漏杀；
  - 杀净所有 run.py + mdns_advertise.py 后统一重启，根治重复进程堆积。
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(BASE, "venv", "Scripts", "python.exe")
RUN = os.path.join(BASE, "run.py")
MDNS = os.path.join(BASE, "mdns_advertise.py")
LOG_DIR = os.path.join(BASE, "logs")
VOICE_LOG = os.path.join(LOG_DIR, "voice-bridge.log")
MDNS_LOG = os.path.join(LOG_DIR, "mdns.log")

HEALTH_URL = "http://127.0.0.1:8710/api/v1/health"
HOST = "voicebridge.local"


def banner(msg):
    print("=" * 44)
    print(msg)
    print("=" * 44)


def check_port_8710():
    """8710 端口是否有 LISTENING。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, timeout=10
        ).stdout.decode("gbk", errors="replace")
        return any(":8710" in line and "LISTENING" in line for line in out.splitlines())
    except Exception:
        return False


def check_health():
    """健康接口是否 200。"""
    import urllib.request
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def check_mdns_resolve():
    """本机能否解析 voicebridge.local。"""
    import socket
    try:
        socket.gethostbyname(HOST)
        return True
    except Exception:
        return False


def find_vb_pids():
    """找出所有 run.py / mdns_advertise.py 的 PID（精确匹配命令行）。"""
    pids = []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, timeout=15,
        ).stdout.decode("gbk", errors="replace")
        for line in out.splitlines():
            low = line.lower()
            if "run.py" in low or "mdns_advertise" in low:
                # csv 格式：Node,CommandLine,ProcessId（第一列是节点名）
                parts = line.split(",")
                try:
                    pid = int(parts[-1].strip())
                    if pid > 0:
                        pids.append(pid)
                except (ValueError, IndexError):
                    continue
    except Exception:
        pass
    return sorted(set(pids))


def kill_pids(pids):
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            print(f"    已杀 PID {pid}")
        except Exception as e:
            print(f"    杀 PID {pid} 失败: {e}")


def start_services():
    os.makedirs(LOG_DIR, exist_ok=True)
    # 用 CREATE_NEW_PROCESS_GROUP + DETACHED 启动独立进程，脚本退出后服务继续跑
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    # 独立打开日志文件句柄（二进制追加，避免编码/占用冲突），进程持有句柄
    vl = open(VOICE_LOG, "ab")
    ml = open(MDNS_LOG, "ab")
    subprocess.Popen([PY, RUN], stdout=vl, stderr=subprocess.STDOUT,
                     cwd=BASE, creationflags=flags)
    subprocess.Popen([PY, MDNS], stdout=ml, stderr=subprocess.STDOUT,
                     cwd=BASE, creationflags=flags)
    # 父进程关闭句柄（子进程已继承），子进程继续写
    vl.close()
    ml.close()
    print("    已启动 run.py + mdns_advertise.py")


def main():
    banner("voice-bridge 自助诊断修复")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    port_ok = check_port_8710()
    health_ok = check_health()
    mdns_ok = check_mdns_resolve()

    print("[1/3] 8710 端口:", "OK" if port_ok else "FAIL（语音服务没监听）")
    print("[2/3] 健康接口:", "OK" if health_ok else "FAIL（服务不可用）")
    print("[3/3] voicebridge.local 解析:", "OK" if mdns_ok else "FAIL（mDNS 广播挂了）")
    print()

    if port_ok and health_ok and mdns_ok:
        banner("全部正常，无需修复")
        print("如果 BOX-3 屏幕仍不是笑脸：")
        print("  - iPhone 热点开着吗？电脑连的是 v2 吗？")
        print("  - BOX-3 连上 WiFi 了吗？")
        print("  - 问天气需要开 Clash")
    else:
        banner("发现异常，正在修复")
        pids = find_vb_pids()
        print(f"找到残留进程 {len(pids)} 个: {pids}")
        if pids:
            print("杀掉残留进程...")
            kill_pids(pids)
            time.sleep(2)
        print("重新启动服务...")
        start_services()
        print("等待 15 秒让服务启动...")
        time.sleep(15)
        banner("复查")
        port_ok2 = check_port_8710()
        health_ok2 = check_health()
        print("[复查] 8710 端口:", "OK" if port_ok2 else "FAIL")
        print("[复查] 健康接口:", "OK" if health_ok2 else "FAIL")
        if port_ok2 and health_ok2:
            print("修复成功！等 30 秒看 BOX-3 屏幕是否变回笑脸。")
        else:
            print("修复后仍异常，可能环境问题（见下方排查）")

    print()
    banner("下一步")
    print("1. 等 30 秒看 BOX-3 屏幕是否变回笑脸")
    print("2. 还不行就：")
    print("   - iPhone 热点开了吗？电脑连 v2 吗？")
    print("   - 重启 BOX-3（拔插 USB / 按 reset）")
    print("   - 问天气要开 Clash")
    print("3. 仍不行：把本窗口截图发给开发")
    print()

    if sys.stdin.isatty():
        input("按回车退出...")


if __name__ == "__main__":
    main()
