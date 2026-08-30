import argparse
import csv
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile


class LocalConfigError(ValueError):
    """The local voice-agent configuration is missing or invalid."""


@dataclass(frozen=True)
class WifiCredential:
    ssid: str
    password: str
    priority: int
    auth_type: int


@dataclass(frozen=True)
class LocalVoiceConfig:
    wifi: tuple[WifiCredential, ...]
    device_token: str


@dataclass(frozen=True)
class NvsImageResult:
    output_path: Path
    sha256: str
    command: tuple[str, ...]


def load_local_config(path):
    config_path = Path(path)
    if not config_path.is_file():
        raise LocalConfigError(f"local config file not found: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalConfigError(f"unable to read local config: {config_path}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("wifi"), list):
        raise LocalConfigError("local config must contain a wifi list")
    try:
        wifi = tuple(
            WifiCredential(
                ssid=entry["ssid"],
                password=entry["password"],
                priority=entry["priority"],
                auth_type=entry["auth_type"],
            )
            for entry in raw["wifi"]
        )
        return LocalVoiceConfig(wifi=wifi, device_token=raw["device_token"])
    except (KeyError, TypeError) as exc:
        raise LocalConfigError("local config fields are missing or malformed") from exc


def validate_local_config(config):
    if isinstance(config, LocalVoiceConfig):
        token = config.device_token
        wifi = config.wifi
    elif isinstance(config, dict):
        token = config.get("device_token")
        wifi = config.get("wifi")
    else:
        raise LocalConfigError("local config must be a JSON object")
    if not isinstance(token, str) or not token:
        raise LocalConfigError("device_token must be a non-empty string")
    if not isinstance(wifi, (list, tuple)):
        raise LocalConfigError("wifi must be a list")
    if len(wifi) > 8:
        raise LocalConfigError("wifi must contain at most 8 entries")
    for index, entry in enumerate(wifi):
        if isinstance(entry, WifiCredential):
            ssid = entry.ssid
            password = entry.password
            priority = entry.priority
            auth_type = entry.auth_type
        elif isinstance(entry, dict):
            ssid = entry.get("ssid")
            password = entry.get("password")
            priority = entry.get("priority")
            auth_type = entry.get("auth_type")
        else:
            raise LocalConfigError(f"wifi[{index}] must be an object")
        if not isinstance(ssid, str):
            raise LocalConfigError(f"wifi[{index}] SSID must be a string")
        if len(ssid.encode("utf-8")) > 32:
            raise LocalConfigError(f"wifi[{index}] SSID exceeds 32 UTF-8 bytes")
        if not isinstance(password, str):
            raise LocalConfigError(f"wifi[{index}] password must be a string")
        if len(password.encode("utf-8")) > 64:
            raise LocalConfigError(
                f"wifi[{index}] password exceeds 64 UTF-8 bytes"
            )
        if type(priority) is not int or not 0 <= priority <= 255:
            raise LocalConfigError(f"wifi[{index}] priority must fit u8")
        if type(auth_type) is not int or not 0 <= auth_type <= 255:
            raise LocalConfigError(f"wifi[{index}] auth_type must fit u8")


LOGGER = logging.getLogger("build_voice")
NVS_NAMESPACE = "voice_cfg"
NVS_PARTITION_SIZE = 0x6000


def generate_nvs_image(config, output_path):
    validate_local_config(config)
    if not isinstance(config, LocalVoiceConfig):
        raise LocalConfigError("generate_nvs_image requires LocalVoiceConfig")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    generator = Path(IDF_PATH) / "components" / "nvs_flash" / (
        "nvs_partition_generator"
    ) / "nvs_partition_gen.py"
    python = Path(VENV_SCRIPTS) / "python.exe"

    with tempfile.TemporaryDirectory(prefix="voice-agent-nvs-") as temp_dir:
        csv_path = Path(temp_dir) / "voice_agent_nvs.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("key", "type", "encoding", "value"))
            writer.writerow((NVS_NAMESPACE, "namespace", "", ""))
            writer.writerow(("count", "data", "u8", len(config.wifi)))
            for index, credential in enumerate(config.wifi):
                writer.writerow((f"ssid_{index}", "data", "string", credential.ssid))
                writer.writerow(
                    (f"pass_{index}", "data", "string", credential.password)
                )
                writer.writerow(
                    (f"prio_{index}", "data", "u8", credential.priority)
                )
                writer.writerow(
                    (f"auth_{index}", "data", "u8", credential.auth_type)
                )
            writer.writerow(("device_token", "data", "string", config.device_token))

        command = (
            str(python),
            str(generator),
            "generate",
            str(csv_path),
            str(output),
            hex(NVS_PARTITION_SIZE),
        )
        completed = subprocess.run(
            list(command),
            cwd=str(output.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            output.unlink(missing_ok=True)
            raise LocalConfigError(
                f"NVS generator failed with exit code {completed.returncode}"
            )

    digest = hashlib.sha256(output.read_bytes()).hexdigest().upper()
    LOGGER.info(
        "NVS image generated: wifi_entries=%d output=%s sha256=%s",
        len(config.wifi),
        output,
        digest,
    )
    return NvsImageResult(output_path=output, sha256=digest, command=command)

VENV_SCRIPTS = r"D:\esp-idf-tools\python_env\idf5.2_py3.11_env\Scripts"
IDF_PATH = r"D:\esp-idf-tools\frameworks\esp-idf-v5.2.7"
PROJ = r"D:\esp-box\examples\voice_agent"
LOG = os.path.join(os.environ.get("TEMP", "."), "v04-voice.log")
DEFAULT_LOCAL_CONFIG = Path(r"D:\esp-box\voice_agent.local.json")
DEFAULT_NVS_OUTPUT = Path(r"D:\esp-box\build_voice_nvs.bin")

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
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"
# components.espressif.com 需走 Clash 代理（若组件缓存不足触发下载）
env["HTTPS_PROXY"] = "http://127.0.0.1:7800"
env["HTTP_PROXY"] = "http://127.0.0.1:7800"
env["NO_PROXY"] = "localhost,127.0.0.1"

def run(name, args, cwd, logf):
    logf.write(f"\n===== {name} =====\n")
    logf.flush()
    r = subprocess.run(args, cwd=cwd, env=env, stdout=logf, stderr=subprocess.STDOUT)
    logf.write(f"\n{name}_EXIT={r.returncode}\n")
    logf.flush()
    return r.returncode


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build and optionally flash BOX-3")
    parser.add_argument("--local-config", type=Path, default=DEFAULT_LOCAL_CONFIG)
    parser.add_argument("--nvs-output", type=Path, default=DEFAULT_NVS_OUTPUT)
    parser.add_argument("--port", default=os.environ.get("ESP_PORT", "COM5"))
    parser.add_argument("--flash", action="store_true")
    return parser.parse_args(argv)


def find_partition_offset(partition_table_path, partition_name):
    path = Path(partition_table_path)
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = csv.reader(line for line in stream if not line.lstrip().startswith("#"))
            for row in rows:
                if len(row) >= 5 and row[0].strip() == partition_name:
                    raw_offset = row[3].strip()
                    if not raw_offset:
                        raise LocalConfigError(
                            f"partition {partition_name} has no explicit offset"
                        )
                    return int(raw_offset, 0)
    except (OSError, UnicodeError, ValueError) as exc:
        raise LocalConfigError("unable to read partition table") from exc
    raise LocalConfigError(f"partition not found: {partition_name}")


def build_and_maybe_flash(args, config, *, command_runner=run):
    py = os.path.join(VENV_SCRIPTS, "python.exe")
    with open(LOG, "w", encoding="utf-8", errors="replace") as logf:
        rc = command_runner(
            "BUILD",
            [py, os.path.join(IDF_PATH, "tools", "idf.py"),
             "-B", "build_v1", "build"],
            PROJ,
            logf,
        )

        flash_args = os.path.join(PROJ, "build_v1", "flasher_args.json")
        if rc == 0 and not os.path.exists(flash_args):
            logf.write("\nBUILD_FAKE_SUCCESS: no flasher_args.json, aborting\n")
            rc = 1

        if rc == 0:
            nvs_result = generate_nvs_image(config, args.nvs_output)
            logf.write(
                "\nNVS_IMAGE "
                f"wifi_entries={len(config.wifi)} "
                f"output={nvs_result.output_path} "
                f"sha256={nvs_result.sha256}\n"
            )
            logf.flush()
            if args.flash:
                nvs_offset = find_partition_offset(
                    Path(PROJ) / "partitions.csv", "nvs"
                )
                rc = command_runner(
                    "FLASH",
                    [
                        os.path.join(VENV_SCRIPTS, "esptool.exe"),
                        "--chip",
                        "esp32s3",
                        "-p",
                        args.port,
                        "-b",
                        "460800",
                        "--before=default_reset",
                        "--after=hard_reset",
                        "write_flash",
                        "@flash_project_args",
                        hex(nvs_offset),
                        str(nvs_result.output_path),
                    ],
                    os.path.join(PROJ, "build_v1"),
                    logf,
                )

        logf.write("\nDONE_ALL\n")
    return rc


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_local_config(args.local_config)
        validate_local_config(config)
        rc = build_and_maybe_flash(args, config)
    except LocalConfigError as exc:
        print(f"configuration error: {exc}")
        return 2
    print(f"EXIT={rc} | log: {LOG}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
