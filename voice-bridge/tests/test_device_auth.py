from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import importlib.util
import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.main as main
from app.config import Config, ConfigError


@pytest.fixture(autouse=True)
def restore_main_device_auth_state():
    original = main.app.state.device_auth
    yield
    main.app.state.device_auth = original


@dataclass
class RecordingHealthStore:
    calls: list[tuple[float | None, float | None, int | None, int | None, float]] = field(
        default_factory=list
    )

    def update(
        self,
        hr: float | None,
        spo2: float | None,
        seq: int | None = None,
        flags: int | None = None,
        quality: float = 1.0,
    ) -> None:
        self.calls.append((hr, spo2, seq, flags, quality))


@pytest.fixture
def health_client(monkeypatch):
    store = RecordingHealthStore()
    monkeypatch.setattr(main, "health_store", store)
    device_auth = importlib.import_module("app.device_auth")
    device_auth.install_device_auth(
        main.app, token="server-token", mode="observe"
    )
    return TestClient(main.app), store


@pytest.mark.parametrize(
    "payload",
    [
        {"hr": 19, "spo2": None, "seq": 0, "flags": 1, "quality": 1.0},
        {"hr": 251, "spo2": None, "seq": 0, "flags": 1, "quality": 1.0},
        {"hr": None, "spo2": 49, "seq": 0, "flags": 2, "quality": 1.0},
        {"hr": None, "spo2": 101, "seq": 0, "flags": 2, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": -1, "flags": 3, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": 256, "flags": 3, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": 0, "flags": -1, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": 0, "flags": 256, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": 0, "flags": 3, "quality": -0.01},
        {"hr": 60, "spo2": 98, "seq": 0, "flags": 3, "quality": 1.01},
        {"hr": None, "spo2": 98, "seq": 0, "flags": 3, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": 0, "flags": 2, "quality": 1.0},
        {"hr": 60, "spo2": None, "seq": 0, "flags": 3, "quality": 1.0},
        {"hr": 60, "spo2": 98, "seq": 0, "flags": 1, "quality": 1.0},
    ],
)
def test_health_data_rejects_out_of_range_values(health_client, payload):
    client, store = health_client

    response = client.post("/api/v1/health/data", json=payload)

    assert response.status_code == 422
    assert store.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"hr": 20, "spo2": 50, "seq": 0, "flags": 3, "quality": 0.0},
        {"hr": 250, "spo2": 100, "seq": 255, "flags": 3, "quality": 1.0},
        {"hr": 60, "spo2": None, "seq": 1, "flags": 1, "quality": 0.5},
        {"hr": None, "spo2": 98, "seq": 2, "flags": 2, "quality": 0.5},
        {"hr": None, "spo2": None, "seq": 3, "flags": 0, "quality": 0.0},
    ],
)
def test_health_data_accepts_valid_boundaries(health_client, payload):
    client, store = health_client

    response = client.post("/api/v1/health/data", json=payload)

    assert response.status_code == 200
    assert store.calls == [
        (
            payload["hr"],
            payload["spo2"],
            payload["seq"],
            payload["flags"],
            payload["quality"],
        )
    ]


def make_auth_client(token: str | None, mode: str):
    assert importlib.util.find_spec("app.device_auth") is not None, (
        "app.device_auth is missing"
    )
    device_auth = importlib.import_module("app.device_auth")
    protected_app = FastAPI()
    device_auth.install_device_auth(protected_app, token=token, mode=mode)

    @protected_app.get(
        "/protected", dependencies=[Depends(device_auth.require_device_token)]
    )
    def protected():
        return {"status": "ok"}

    return TestClient(protected_app)


def test_auth_rejects_empty_server_configuration_without_leaking_details():
    client = make_auth_client(None, "required")

    response = client.get(
        "/protected", headers={"X-Device-Token": "request-token"}
    )

    assert response.status_code == 503
    assert "request-token" not in response.text


def test_observe_mode_allows_missing_header_but_rejects_wrong_token(caplog):
    client = make_auth_client("server-token", "observe")
    caplog.set_level(logging.WARNING)

    missing = client.get("/protected")
    wrong = client.get(
        "/protected", headers={"X-Device-Token": "wrong-request-token"}
    )
    correct = client.get(
        "/protected", headers={"X-Device-Token": "server-token"}
    )

    assert missing.status_code == 200
    assert wrong.status_code == 403
    assert correct.status_code == 200
    assert "wrong-request-token" not in caplog.text
    assert "server-token" not in caplog.text


def test_required_mode_enforces_missing_wrong_and_correct_statuses():
    client = make_auth_client("server-token", "required")

    missing = client.get("/protected")
    wrong = client.get(
        "/protected", headers={"X-Device-Token": "wrong-request-token"}
    )
    correct = client.get(
        "/protected", headers={"x-device-token": "server-token"}
    )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert correct.status_code == 200


def test_duplicate_device_token_header_is_rejected():
    client = make_auth_client("server-token", "required")

    response = client.get(
        "/protected",
        headers=[
            ("X-Device-Token", "server-token"),
            ("X-Device-Token", "server-token"),
        ],
    )

    assert response.status_code == 400


def test_config_reads_device_token_and_observe_override_from_environment(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "device_auth:\n"
        "  mode: required\n"
        "  token_env: DEVICE_TOKEN\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEVICE_AUTH_MODE", "observe")
    monkeypatch.setenv("DEVICE_TOKEN", "server-token")

    config = Config(config_path)

    assert config.device_auth_mode == "observe"
    assert config.device_token() == "server-token"


def test_config_rejects_unknown_device_auth_mode(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("device_auth:\n  mode: required\n", encoding="utf-8")
    monkeypatch.setenv("DEVICE_AUTH_MODE", "disabled")

    with pytest.raises(ConfigError, match="observe or required"):
        Config(config_path)


def test_wechat_chat_id_comes_from_local_environment_not_tracked_yaml(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "health:\n"
        "  wechat_chat_id: tracked-placeholder\n"
        "  wechat_push_enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WECHAT_CHAT_ID", "local-chat-id")

    config = Config(config_path)

    assert config.health_wechat_chat_id == "local-chat-id"


def test_config_rejects_enabled_wechat_push_without_local_recipient(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "health:\n  wechat_push_enabled: true\n", encoding="utf-8"
    )
    monkeypatch.setattr(Config, "_read_key", lambda self, name: None)

    with pytest.raises(ConfigError, match="WECHAT_CHAT_ID"):
        Config(config_path)


def test_main_health_route_enforces_required_mode_missing_header(monkeypatch):
    store = RecordingHealthStore()
    monkeypatch.setattr(main, "health_store", store)
    device_auth = importlib.import_module("app.device_auth")
    device_auth.install_device_auth(
        main.app, token="server-token", mode="required"
    )
    client = TestClient(main.app)

    response = client.post(
        "/api/v1/health/data",
        json={"hr": 60, "spo2": 98, "seq": 0, "flags": 3, "quality": 1.0},
    )

    assert response.status_code == 401
    assert store.calls == []


def test_every_existing_device_route_rejects_wrong_token_before_business_logic():
    device_auth = importlib.import_module("app.device_auth")
    device_auth.install_device_auth(
        main.app, token="server-token", mode="observe"
    )
    client = TestClient(main.app, raise_server_exceptions=False)
    headers = {"X-Device-Token": "wrong-request-token"}

    responses = [
        client.post(
            "/api/v1/health/data",
            json={
                "hr": 60,
                "spo2": 98,
                "seq": 0,
                "flags": 3,
                "quality": 1.0,
            },
            headers=headers,
        ),
        client.get("/api/v1/health/alert", headers=headers),
        client.post("/api/v1/voice/chat", headers=headers),
        client.post("/api/v1/voice/chat/stream", headers=headers),
        client.post(
            "/api/v1/voice/stream",
            content=b"\x00\x00",
            headers={**headers, "Content-Type": "application/octet-stream"},
        ),
    ]

    assert [response.status_code for response in responses] == [403] * 5
    assert all("wrong-request-token" not in response.text for response in responses)


def test_public_runtime_health_does_not_require_device_token():
    device_auth = importlib.import_module("app.device_auth")
    device_auth.install_device_auth(
        main.app, token="server-token", mode="required"
    )

    response = TestClient(main.app).get("/api/v1/health")

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("token", "mode", "expected"),
    [
        ("server-token", "observe", "degraded"),
        ("server-token", "required", "ok"),
        (None, "required", "unavailable"),
    ],
)
def test_runtime_health_reports_safe_device_auth_state(token, mode, expected):
    device_auth = importlib.import_module("app.device_auth")
    device_auth.install_device_auth(main.app, token=token, mode=mode)

    response = TestClient(main.app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["device_auth"] == expected
    assert "server-token" not in response.text
