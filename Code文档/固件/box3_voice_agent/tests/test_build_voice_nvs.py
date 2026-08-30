import importlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


MIGRATION_TOOL = Path(r"D:\esp-box\tools\migrate_voice_credentials.py")


@pytest.fixture
def build_voice():
    sys.modules.pop("build_voice", None)
    return importlib.import_module("build_voice")


def test_load_local_config_rejects_missing_file(build_voice, tmp_path):
    assert hasattr(build_voice, "LocalConfigError"), "LocalConfigError is missing"
    assert hasattr(build_voice, "load_local_config"), "load_local_config is missing"

    with pytest.raises(build_voice.LocalConfigError):
        build_voice.load_local_config(tmp_path / "missing.json")


def test_import_does_not_start_build_or_flash(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or SimpleNamespace(returncode=1),
    )
    sys.modules.pop("build_voice", None)

    importlib.import_module("build_voice")

    assert calls == []
    assert not (tmp_path / "v04-voice.log").exists()


def test_build_environment_forces_python_utf8(build_voice):
    assert build_voice.env.get("PYTHONUTF8") == "1"
    assert build_voice.env.get("PYTHONIOENCODING") == "utf-8"


def test_validate_local_config_rejects_empty_device_token(build_voice, tmp_path):
    config_path = tmp_path / "voice_agent.local.json"
    config_path.write_text(
        json.dumps(
            {
                "wifi": [
                    {
                        "ssid": "test-network",
                        "password": "test-password",
                        "priority": 1,
                        "auth_type": 0,
                    }
                ],
                "device_token": "",
            }
        ),
        encoding="utf-8",
    )

    config = build_voice.load_local_config(config_path)

    assert hasattr(build_voice, "validate_local_config")
    with pytest.raises(build_voice.LocalConfigError, match="device_token"):
        build_voice.validate_local_config(config)


def test_validate_local_config_rejects_more_than_eight_wifi_entries(build_voice):
    config = {
        "wifi": [
            {
                "ssid": f"network-{index}",
                "password": "test-password",
                "priority": index + 1,
                "auth_type": 0,
            }
            for index in range(9)
        ],
        "device_token": "test-device-token",
    }

    with pytest.raises(build_voice.LocalConfigError, match="at most 8"):
        build_voice.validate_local_config(config)


def test_validate_local_config_rejects_ssid_over_32_utf8_bytes(build_voice):
    config = {
        "wifi": [
            {
                "ssid": "网" * 11,
                "password": "test-password",
                "priority": 1,
                "auth_type": 0,
            }
        ],
        "device_token": "test-device-token",
    }

    with pytest.raises(build_voice.LocalConfigError, match="SSID.*32 UTF-8 bytes"):
        build_voice.validate_local_config(config)


def test_validate_local_config_rejects_password_over_64_utf8_bytes(build_voice):
    config = {
        "wifi": [
            {
                "ssid": "test-network",
                "password": "密" * 22,
                "priority": 1,
                "auth_type": 0,
            }
        ],
        "device_token": "test-device-token",
    }

    with pytest.raises(build_voice.LocalConfigError, match="password.*64 UTF-8 bytes"):
        build_voice.validate_local_config(config)


def test_load_local_config_returns_typed_validated_fields(build_voice, tmp_path):
    config_path = tmp_path / "voice_agent.local.json"
    config_path.write_text(
        json.dumps(
            {
                "wifi": [
                    {
                        "ssid": "test-network",
                        "password": "test-password",
                        "priority": 2,
                        "auth_type": 3,
                    }
                ],
                "device_token": "test-device-token",
            }
        ),
        encoding="utf-8",
    )

    config = build_voice.load_local_config(config_path)
    build_voice.validate_local_config(config)

    assert isinstance(config, build_voice.LocalVoiceConfig)
    assert config.device_token == "test-device-token"
    assert config.wifi[0].ssid == "test-network"
    assert config.wifi[0].password == "test-password"
    assert config.wifi[0].priority == 2
    assert config.wifi[0].auth_type == 3


def test_generate_nvs_image_keeps_secrets_out_of_command_and_log(
    build_voice, tmp_path, caplog
):
    password = "private-wifi-value"
    token = "private-device-token"
    config_path = tmp_path / "voice_agent.local.json"
    config_path.write_text(
        json.dumps(
            {
                "wifi": [
                    {
                        "ssid": "test-network",
                        "password": password,
                        "priority": 1,
                        "auth_type": 0,
                    }
                ],
                "device_token": token,
            }
        ),
        encoding="utf-8",
    )
    config = build_voice.load_local_config(config_path)
    output_path = tmp_path / "build_voice_nvs.bin"
    caplog.set_level(logging.INFO)

    assert hasattr(build_voice, "generate_nvs_image")
    result = build_voice.generate_nvs_image(config, output_path)

    assert output_path.stat().st_size == 0x6000
    representation = " ".join(result.command) + "\n" + caplog.text
    assert password not in representation
    assert token not in representation
    assert len(result.sha256) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    (("priority", -1), ("priority", 256), ("auth_type", -1), ("auth_type", 256)),
)
def test_validate_local_config_rejects_values_that_do_not_fit_u8(
    build_voice, field, value
):
    entry = {
        "ssid": "test-network",
        "password": "test-password",
        "priority": 1,
        "auth_type": 0,
    }
    entry[field] = value
    config = {"wifi": [entry], "device_token": "test-device-token"}

    with pytest.raises(build_voice.LocalConfigError, match=field):
        build_voice.validate_local_config(config)


def test_migration_writes_local_config_without_printing_secrets(tmp_path, capsys):
    assert MIGRATION_TOOL.is_file(), "migration tool is missing"
    spec = importlib.util.spec_from_file_location(
        "migrate_voice_credentials", MIGRATION_TOOL
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_path = tmp_path / "voice_agent.c"
    source_text = """
static const wifi_cred_t DEFAULT_WIFI_CREDS[2] = {
    { "network-a", "secret-a", 1, 0 },
    { "network-b", "secret-b", 2, 3 },
};
"""
    source_path.write_text(source_text, encoding="utf-8")
    output_path = tmp_path / "voice_agent.local.json"
    acl_paths = []

    result = module.migrate_credentials(
        source_path,
        output_path,
        token_factory=lambda: "generated-device-token",
        acl_setter=lambda path: acl_paths.append(path),
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert result.wifi_count == 2
    assert saved["wifi"] == [
        {
            "ssid": "network-a",
            "password": "secret-a",
            "priority": 1,
            "auth_type": 0,
        },
        {
            "ssid": "network-b",
            "password": "secret-b",
            "priority": 2,
            "auth_type": 3,
        },
    ]
    assert saved["device_token"] == "generated-device-token"
    assert len(acl_paths) == 1
    assert source_path.read_text(encoding="utf-8") == source_text
    assert "secret-a" not in captured.out + captured.err
    assert "generated-device-token" not in captured.out + captured.err


def test_migration_resolves_numeric_auth_type_macro():
    spec = importlib.util.spec_from_file_location(
        "migrate_voice_credentials_macro", MIGRATION_TOOL
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_text = """
#define WIFI_AUTH_WPA2_PSK_T 0
static const wifi_cred_t DEFAULT_WIFI_CREDS[1] = {
    { "network-a", "secret-a", 1, WIFI_AUTH_WPA2_PSK_T },
};
"""

    credentials = module.parse_legacy_credentials(source_text)

    assert credentials == [
        {
            "ssid": "network-a",
            "password": "secret-a",
            "priority": 1,
            "auth_type": 0,
        }
    ]


def test_migration_parse_failure_leaves_source_and_output_untouched(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "migrate_voice_credentials_failure", MIGRATION_TOOL
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_path = tmp_path / "voice_agent.c"
    source_text = "static const char *unrelated = \"unchanged\";\n"
    source_path.write_text(source_text, encoding="utf-8")
    output_path = tmp_path / "voice_agent.local.json"

    with pytest.raises(module.MigrationError, match="DEFAULT_WIFI_CREDS"):
        module.migrate_credentials(
            source_path,
            output_path,
            token_factory=lambda: "unused-token",
            acl_setter=lambda path: None,
        )

    assert source_path.read_text(encoding="utf-8") == source_text
    assert not output_path.exists()


def test_parse_args_supports_local_config_nvs_output_and_flash(build_voice, tmp_path):
    local_config = tmp_path / "local.json"
    nvs_output = tmp_path / "local.bin"

    assert hasattr(build_voice, "parse_args")
    args = build_voice.parse_args(
        [
            "--local-config",
            str(local_config),
            "--nvs-output",
            str(nvs_output),
            "--port",
            "COM9",
            "--flash",
        ]
    )

    assert args.local_config == local_config
    assert args.nvs_output == nvs_output
    assert args.port == "COM9"
    assert args.flash is True


def test_build_pipeline_builds_and_generates_nvs_without_flashing(
    build_voice, tmp_path, monkeypatch
):
    project = tmp_path / "voice_agent"
    build_dir = project / "build_v1"
    project.mkdir()
    monkeypatch.setattr(build_voice, "PROJ", str(project))
    monkeypatch.setattr(build_voice, "LOG", str(tmp_path / "build.log"))
    calls = []

    def fake_runner(name, command, cwd, log_stream):
        calls.append((name, tuple(command), Path(cwd)))
        if name == "BUILD":
            build_dir.mkdir()
            (build_dir / "flasher_args.json").write_text("{}", encoding="utf-8")
        return 0

    config = build_voice.LocalVoiceConfig(
        wifi=(build_voice.WifiCredential("network", "password", 1, 0),),
        device_token="device-token",
    )
    args = build_voice.parse_args(
        ["--nvs-output", str(tmp_path / "local.bin")]
    )

    assert hasattr(build_voice, "build_and_maybe_flash")
    rc = build_voice.build_and_maybe_flash(args, config, command_runner=fake_runner)

    assert rc == 0
    assert [call[0] for call in calls] == ["BUILD"]
    assert (tmp_path / "local.bin").stat().st_size == 0x6000
    log_text = (tmp_path / "build.log").read_text(encoding="utf-8")
    assert "wifi_entries=1" in log_text
    assert "password" not in log_text
    assert "device-token" not in log_text


def test_find_partition_offset_reads_named_nvs_partition(build_voice, tmp_path):
    partition_table = tmp_path / "partitions.csv"
    partition_table.write_text(
        "# Name,Type,SubType,Offset,Size,Flags\n"
        "nvs,data,nvs,0x9000,0x6000,\n"
        "factory,app,factory,0x10000,4096k,\n",
        encoding="utf-8",
    )

    assert hasattr(build_voice, "find_partition_offset")
    assert build_voice.find_partition_offset(partition_table, "nvs") == 0x9000


def test_flash_pipeline_writes_app_and_nvs_at_partition_offset(
    build_voice, tmp_path, monkeypatch
):
    project = tmp_path / "voice_agent"
    build_dir = project / "build_v1"
    project.mkdir()
    (project / "partitions.csv").write_text(
        "nvs,data,nvs,0x9000,0x6000,\n", encoding="utf-8"
    )
    monkeypatch.setattr(build_voice, "PROJ", str(project))
    monkeypatch.setattr(build_voice, "LOG", str(tmp_path / "flash.log"))
    calls = []

    def fake_runner(name, command, cwd, log_stream):
        calls.append((name, tuple(command), Path(cwd)))
        if name == "BUILD":
            build_dir.mkdir()
            (build_dir / "flasher_args.json").write_text("{}", encoding="utf-8")
        return 0

    config = build_voice.LocalVoiceConfig(
        wifi=(build_voice.WifiCredential("network", "password", 1, 0),),
        device_token="device-token",
    )
    nvs_output = tmp_path / "local.bin"
    args = build_voice.parse_args(
        [
            "--nvs-output",
            str(nvs_output),
            "--port",
            "COM9",
            "--flash",
        ]
    )

    rc = build_voice.build_and_maybe_flash(args, config, command_runner=fake_runner)

    assert rc == 0
    assert [call[0] for call in calls] == ["BUILD", "FLASH"]
    flash_command = calls[1][1]
    assert "COM9" in flash_command
    assert "@flash_project_args" in flash_command
    assert "0x9000" in flash_command
    assert str(nvs_output.resolve()) in flash_command
    representation = " ".join(flash_command) + (tmp_path / "flash.log").read_text(
        encoding="utf-8"
    )
    assert "password" not in representation
    assert "device-token" not in representation
