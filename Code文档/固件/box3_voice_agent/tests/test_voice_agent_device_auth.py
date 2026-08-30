from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "examples" / "voice_agent" / "main"


def source(name: str) -> str:
    return (MAIN / name).read_text(encoding="utf-8")


def function_body(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unterminated function: {signature}")


def test_shared_auth_client_has_missing_token_selftest_and_no_secret_logs():
    header = source("device_auth_client.h")
    implementation = source("device_auth_client.c")

    assert "device_auth_client_init" in header
    assert "add_device_auth_header" in header
    assert "open_authenticated_http" in header
    assert "credential_store_load_device_token" in implementation
    assert '"X-Device-Token"' in implementation
    assert "ESP_ERR_NOT_FOUND" in implementation
    assert "device_auth_client_selftest" in implementation
    assert "open_authenticated_http" in function_body(
        implementation, "esp_err_t device_auth_client_selftest(void)"
    )
    for forbidden in ("ESP_LOG_BUFFER", "device token: %s", "token=%s"):
        assert forbidden not in implementation


def test_protected_voice_and_alert_requests_use_authenticated_open():
    implementation = source("voice_agent.c")

    voice = function_body(
        implementation,
        "static void voice_round(uint32_t capture_generation)",
    )
    alert = function_body(implementation, "static void alert_poll_once(void)")
    public_health = function_body(implementation, "static bool health_probe_ok(void)")

    assert "open_authenticated_http(client, -1)" in voice
    assert "open_authenticated_http(client, 0)" in alert
    assert "esp_http_client_open(client, 0)" in public_health
    assert "open_authenticated_http" not in public_health


def test_health_upload_uses_same_authenticated_open_helper():
    implementation = source("ble_central.c")
    upload = function_body(implementation, "static bool http_post_health")

    assert '#include "device_auth_client.h"' in implementation
    assert "open_authenticated_http(client, wlen)" in upload


def test_device_token_is_loaded_once_after_nvs_init_and_module_is_built():
    implementation = source("voice_agent.c")
    app_main = function_body(implementation, "void app_main(void)")
    cmake = source("CMakeLists.txt")

    assert app_main.index("wifi_init();") < app_main.index("device_auth_client_init()")
    assert app_main.count("device_auth_client_init()") == 1
    assert '"device_auth_client.c"' in cmake
