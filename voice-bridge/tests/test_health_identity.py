"""Source identity, original age and protected observation contract."""
import pytest
from pydantic import ValidationError
from app.schemas import HealthDataIn
from app.health import HealthDataStore

BOOT = "a" * 32
OTHER = "b" * 32


def source(index, *, epoch=BOOT + ":1", age=0):
    return dict(source_epoch=epoch, source_index=index, source_age_ms=age)


def store():
    clock, alerts = [100.0], []
    value = HealthDataStore(monotonic=lambda: clock[0], alert_cb=alerts.append)
    value.data_stale_seconds = 60.0
    return value, clock, alerts


def test_legacy_reposts_do_not_count_or_refresh_fields():
    s, clock, alerts = store()
    s.update(120, 90, 100)
    clock[0] += 10
    assert s.update(120, 90, 100) == "duplicate"
    s.update(120, 90, 100)
    assert not alerts and s.get_latest_fields().hr_age_s == 10
    s.update(120, 90, 101); s.update(120, 90, 102)
    assert len(alerts) == 1


def test_no_seq_cannot_confirm_repeated_abnormal_frames():
    s, _, alerts = store()
    for _ in range(4): s.update(120, 90)
    assert not alerts


def test_enhanced_duplicate_conflict_and_retired_epoch():
    s, clock, alerts = store()
    assert s.update(120, 90, 255, **source(255)) == "ok"
    clock[0] += 10
    assert s.update(120, 90, 255, **source(255, age=10000)) == "duplicate"
    assert s.get_latest_fields().hr_age_s == 10 and not alerts
    from app.health import HealthIdentityError
    with pytest.raises(HealthIdentityError, match="identity_conflict"):
        s.update(121, 90, 255, **source(255))
    assert s.update(120, 90, 0, **source(256)) == "ok"
    s.update(120, 90, 1, **source(257)); assert len(alerts) == 1
    s.update(120, 90, 0, **source(0, epoch=BOOT + ":2"))
    assert s.get_latest_fields().hr == 120
    with pytest.raises(HealthIdentityError, match="stale_identity"):
        s.update(120, 90, 2, **source(258))
    s.update(120, 90, 0, **source(0, epoch=OTHER + ":1"))
    with pytest.raises(HealthIdentityError, match="stale_identity"):
        s.update(120, 90, 1, **source(1, epoch=BOOT + ":3"))
    with pytest.raises(HealthIdentityError, match="legacy_after_enhanced"):
        s.update(120, 90, 1)
    assert len(alerts) == 1, "epoch switches cannot bypass the existing cooldown"


def test_source_age_first_upload_and_retry_do_not_refresh_expired_values():
    s, clock, alerts = store()
    s.update(120, 90, 1, **source(1, age=59000))
    assert s.get_latest_fields().hr_age_s == 59
    clock[0] += 2
    s.update(120, 90, 1, **source(1, age=61000))
    assert s.get_fresh_values(60) == (None, None)
    s.update(130, 89, 2, **source(2, age=60001))
    assert s.get_latest_fields().hr == 120 and not alerts
    s.update(None, 90, 3, flags=2, **source(3, age=5000))
    assert s.get_fresh_values(60) == (None, 90)


def test_enhanced_full_seq_wrap_is_new_independent_sample():
    s, _, _ = store()
    s.update(70, 99, 0, **source(0))
    assert s.update(70, 99, 0, **source(256)) == "ok"
    from app.health import HealthIdentityError
    with pytest.raises(HealthIdentityError, match="stale_identity"):
        s.update(70, 99, 0, **source(0))


@pytest.mark.parametrize("mutation", [
    {"source_index": None}, {"source_epoch": None}, {"source_age_ms": None},
    {"source_epoch": "A" * 32 + ":1"}, {"source_epoch": BOOT + ":-1"},
    {"source_epoch": BOOT + ":18446744073709551616"},
    {"source_index": True}, {"source_index": 1.0}, {"source_index": -1},
    {"source_index": 2**63}, {"source_age_ms": True}, {"source_age_ms": 2**63},
    {"seq": None}, {"seq": True}, {"seq": 1.0}, {"source_index": 2},
])
def test_enhanced_schema_rejects_invalid_identity(mutation):
    payload = dict(hr=70, spo2=99, seq=1, **source(1)); payload.update(mutation)
    with pytest.raises(ValidationError): HealthDataIn(**payload)


def test_retired_boot_capacity_is_bounded_without_revival():
    s, _, _ = store()
    for i in range(257):
        assert s.update(70, 99, 0, **source(0, epoch=f"{i:032x}:1")) == "ok"
    from app.health import HealthIdentityError
    with pytest.raises(HealthIdentityError, match="identity_capacity"):
        s.update(70, 99, 0, **source(0, epoch=f"{257:032x}:1"))
    with pytest.raises(HealthIdentityError, match="stale_identity"):
        s.update(70, 99, 0, **source(0, epoch=f"{0:032x}:2"))


def test_legacy_ambiguity_and_inactivity_rebuild_without_alert_confirmation():
    s, clock, alerts = store()
    s.update(120, 90, 100); s.update(120, 90, 101)
    s.update(120, 90, 0); assert not alerts
    s.update(120, 90, 1); s.update(120, 90, 2); s.update(120, 90, 3)
    assert len(alerts) == 1
    clock[0] += 61
    s.update(120, 90, 4)
    assert s._over_count == 0


def test_protected_status_endpoint_is_private_and_readonly(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.device_auth import install_device_auth
    s, clock, _ = store()
    monkeypatch.setattr(main, "health_store", s)
    monkeypatch.setattr(main.cfg, "health_data_stale_seconds", 60, raising=False)
    monkeypatch.setattr(main.app.state, "device_auth", main.app.state.device_auth)
    install_device_auth(main.app, token="fixture-status-key", mode="required")
    client = TestClient(main.app)
    url = "/api/v1/health/data/status"
    assert client.get(url).status_code == 401
    headers = {"X-Device-Token": "fixture-status-key"}
    assert client.get(url, headers=headers).json()["state"] == "no_data"
    s.update(70, None, 1, flags=1, **source(1))
    before = dict(s.__dict__)
    for _ in range(3):
        result = client.get(url, headers=headers)
        assert result.status_code == 200
        assert result.json() == dict(module_ready=True, hr_available=True, spo2_available=False,
                                     source_age_verified=True, state="available")
    assert dict(s.__dict__) == before
    assert "fixture-status-key" not in result.text and BOOT not in result.text
    clock[0] += 61
    assert client.get(url, headers=headers).json()["state"] == "stale"


def test_actual_http_repost_is_idempotent_and_bad_identity_rejected(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.device_auth import install_device_auth
    s, clock, alerts = store()
    monkeypatch.setattr(main, "health_store", s)
    monkeypatch.setattr(main.app.state, "device_auth", main.app.state.device_auth)
    install_device_auth(main.app, token="fixture-status-key", mode="required")
    c = TestClient(main.app); headers={"X-Device-Token": "fixture-status-key"}
    url="/api/v1/health/data"
    payload=dict(hr=120, spo2=90, seq=254, **source(254))
    assert c.post(url, json=payload).status_code == 401
    assert c.post(url, json=payload, headers=headers).json() == {"status":"ok"}
    clock[0] += 5; payload["source_age_ms"] = 5000
    assert c.post(url, json=payload, headers=headers).json() == {"status":"duplicate"}
    assert not alerts and s.get_latest_fields().hr_age_s == 5
    changed=dict(payload, hr=121)
    assert c.post(url, json=changed, headers=headers).status_code == 409
    invalid=dict(payload, source_index=255)
    assert c.post(url, json=invalid, headers=headers).status_code == 422
    for index in (255, 256):
        payload.update(source(index), seq=index & 255)
        assert c.post(url, json=payload, headers=headers).status_code == 200
    assert len(alerts) == 1
    assert c.post(url, json=dict(hr=120, spo2=90, seq=1), headers=headers).status_code == 409


def test_concurrent_same_identity_is_one_independent_sample():
    import threading
    s, _, alerts = store(); gate=threading.Barrier(8); results=[]
    def send(): gate.wait(); results.append(s.update(120,90,1,**source(1)))
    threads=[threading.Thread(target=send) for _ in range(8)]
    for t in threads:t.start()
    for t in threads:t.join(1)
    assert results.count("ok") == 1 and results.count("duplicate") == 7
    assert not alerts and s._over_count == 1


def test_legacy_status_does_not_claim_verified_source_age():
    s, _, _ = store(); s.update(70,99,1)
    assert s.data_status(60)["source_age_verified"] is False


def _accepted_state(value):
    """Rejection must preserve every accepted cache/identity/alert member."""
    import copy
    return {key: copy.deepcopy(item) for key, item in value.__dict__.items()
            if key not in ("_lock", "_monotonic", "_alert_cb")}


@pytest.mark.parametrize("rejection", ["old_generation", "retired_boot", "capacity",
                                      "conflict", "old_index", "legacy_downgrade"])
def test_rejected_http_identity_preserves_state_and_next_episode(monkeypatch, rejection):
    from contextlib import asynccontextmanager
    from fastapi.testclient import TestClient
    from app import main
    from app.device_auth import install_device_auth

    s, clock, alerts = store()
    epoch = BOOT + ":2"
    if rejection == "retired_boot":
        s.update(70, 99, 0, **source(0, epoch=epoch))
        epoch = OTHER + ":2"
    elif rejection == "capacity":
        for i in range(257):
            s.update(70, 99, 0, flags=3, quality=.8, **source(0, epoch=f"{i:032x}:2"))
        epoch = f"{256:032x}:2"

    @asynccontextmanager
    async def synthetic_lifespan(app):
        yield

    monkeypatch.setattr(main.app.router, "lifespan_context", synthetic_lifespan)
    monkeypatch.setattr(main, "health_store", s)
    monkeypatch.setattr(main.app.state, "device_auth", main.app.state.device_auth)
    install_device_auth(main.app, token="fixture-status-key", mode="required")
    headers = {"X-Device-Token": "fixture-status-key"}
    def frame(index, *, hr=120, spo2=90, identity=epoch):
        return dict(hr=hr, spo2=spo2, seq=index & 255, flags=3, quality=.8,
                    **source(index, epoch=identity))

    with TestClient(main.app) as client:
        def post(payload):
            return client.post("/api/v1/health/data", json=payload, headers=headers)
        assert post(frame(0, hr=70, spo2=99)).status_code == 200
        for index in range(1, 4):
            clock[0] += 1
            assert post(frame(index)).status_code == 200
        assert len(alerts) == 1
        clock[0] += 1
        assert post(frame(4, hr=70, spo2=99)).status_code == 200
        rejected = {
            "old_generation": frame(0, identity=BOOT + ":1"),
            "retired_boot": frame(0, identity=BOOT + ":3"),
            "capacity": frame(0, identity=f"{257:032x}:2"),
            "conflict": frame(4),
            "old_index": frame(3),
            "legacy_downgrade": dict(hr=120, spo2=90, seq=5, flags=3, quality=.8),
        }[rejection]
        before = _accepted_state(s)
        response = post(rejected)
        after = _accepted_state(s)
        assert response.status_code == 409
        assert before == after
        for index in range(5, 8):
            clock[0] += 1
            assert post(frame(index)).status_code == 200
        assert len(alerts) == 2


@pytest.mark.parametrize("replacement_epoch", [BOOT + ":3", OTHER + ":1"])
def test_accepted_epoch_switch_keeps_event_cooldown_and_pending_outbox(replacement_epoch):
    s, clock, alerts = store()
    for index in range(3):
        s.update(120, 90, index, **source(index, epoch=BOOT + ":2"))
    assert len(alerts) == 1
    pending = s._legacy_pending.copy()
    last_event = s._last_event_ts
    for index in range(3):
        clock[0] += 1
        s.update(120, 90, index, **source(index, epoch=replacement_epoch))
    assert len(alerts) == 1 and s._last_event_ts == last_event
    assert s._legacy_pending == pending
    clock[0] = last_event + s.alert_cooldown_s
    s.update(120, 90, 3, **source(3, epoch=replacement_epoch))
    assert len(alerts) == 2
