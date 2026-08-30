import os
import subprocess

# 腕部节点（ESP32-C3）构建脚本：默认仅编译，加 --flash 则编译+烧录 COM6
VENV_SCRIPTS = r"D:\esp-idf-tools\python_env\idf5.2_py3.11_env\Scripts"
IDF_PATH = r"D:\esp-idf-tools\frameworks\esp-idf-v5.2.7"
PROJ = r"D:\esp-box\examples\ble_wrist_node"
LOG = os.path.join(os.environ.get("TEMP", "."), "wrist-build.log")
PORT = os.environ.get("ESP_PORT", "COM6")

env = dict(os.environ)
for k in list(env.keys()):
    kl = k.lower()
    if kl == "path" or kl.startswith("msys") or kl.startswith("mingw"):
        del env[k]
for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
    env.pop(k, None)
env["PATH"] = ";".join([
    VENV_SCRIPTS,
    r"D:\esp-idf-tools\tools\xtensa-esp-elf\esp-13.2.0_20250707\xtensa-esp-elf\bin",
    r"D:\esp-idf-tools\tools\riscv32-esp-elf\esp-13.2.0_20250707\riscv32-esp-elf\bin",
    r"D:\esp-idf-tools\tools\esp32ulp-elf\2.35_20220830\esp32ulp-elf\bin",
    r"D:\esp-idf-tools\tools\cmake\3.30.2\bin",
    r"D:\esp-idf-tools\tools\ninja\1.12.1",
    r"D:\esp-idf-tools\tools\idf-exe\1.0.3",
    os.path.join(IDF_PATH, "tools"),
    r"C:\Windows\System32",
    r"C:\Windows",
    r"D:\Git\cmd",
])
env["IDF_PATH"] = IDF_PATH
env["IDF_TOOLS_PATH"] = r"D:\esp-idf-tools"
env["IDF_PYTHON_ENV_PATH"] = r"D:\esp-idf-tools\python_env\idf5.2_py3.11_env"
env["ESP_ROM_ELF_DIR"] = r"D:\esp-idf-tools\tools\esp-rom-elfs\20240305"
env["IDF_CCACHE_ENABLE"] = "0"
env["IDF_TARGET"] = "esp32c3"
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

logf = open(LOG, "w", encoding="utf-8", errors="replace")
py = os.path.join(VENV_SCRIPTS, "python.exe")

flash = "--flash" in os.sys.argv

logf.write("===== BUILD (target=esp32c3) =====\n")
logf.flush()
r = subprocess.run(
    [py, os.path.join(IDF_PATH, "tools", "idf.py"), "-B", "build", "build"],
    cwd=PROJ, env=env, stdout=logf, stderr=subprocess.STDOUT,
)
logf.write(f"\nBUILD_EXIT={r.returncode}\n")
logf.flush()

if flash and r.returncode == 0:
    logf.write(f"===== FLASH (port {PORT}) =====\n")
    logf.flush()
    r2 = subprocess.run(
        [py, os.path.join(IDF_PATH, "tools", "idf.py"), "-B", "build",
         "-p", PORT, "flash"],
        cwd=PROJ, env=env, stdout=logf, stderr=subprocess.STDOUT,
    )
    logf.write(f"\nFLASH_EXIT={r2.returncode}\n")
    logf.flush()
    r = r2

logf.close()
print("EXIT=", r.returncode, "| log:", LOG)
raise SystemExit(r.returncode)
