import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace
from datetime import datetime, timedelta

import app.main as main
from app.alert_outbox import AlertOutbox
from app.device_auth import DeviceAuthState
from app.health import HealthDataStore
from app.pipeline import StreamingPipeline
from app.wechat_alert import WechatAlertPusher, process_wechat_outbox_once


class FakeMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SequentialUUID:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"00000000-0000-4000-8000-{self.value:012d}"


def test_field_timestamps_are_independent() -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)

    store.update(hr=None, spo2=98, seq=1, flags=0x02, quality=0.9)
    clock.advance(600)
    store.update(hr=78, spo2=None, seq=2, flags=0x01, quality=0.9)

    latest = store.get_latest_fields()
    assert latest.hr == 78
    assert latest.hr_age_s == pytest.approx(0)
    assert latest.spo2 == 98
    assert latest.spo2_age_s == pytest.approx(600)
    assert latest.link_age_s == pytest.approx(0)


@pytest.mark.parametrize(
    ("flags", "quality"),
    [
        (0x01 | 0x04, 0.9),
        (0x01, 0.49),
    ],
)
def test_artifact_or_low_quality_frame_does_not_count_as_abnormal(
    flags: int, quality: float
) -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(
        alert_consecutive=1,
        min_quality=0.5,
        monotonic=clock,
    )

    store.update(hr=150, spo2=None, seq=1, flags=flags, quality=quality)

    assert store.poll_alert() is None
    latest = store.get_latest_fields()
    assert latest.link_age_s == pytest.approx(0)
    assert latest.hr is None


def test_data_older_than_thirty_minutes_cannot_generate_alert() -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(
        alert_consecutive=1,
        alert_max_age_s=1800,
        monotonic=clock,
    )
    store.update(hr=150, spo2=None, seq=1, flags=0x01, quality=1.0)

    clock.advance(1801)

    assert store.poll_alert() is None


def test_fresh_values_filter_each_field_at_five_minutes() -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=None, spo2=98, seq=1, flags=0x02, quality=1.0)
    clock.advance(301)
    store.update(hr=76, spo2=None, seq=2, flags=0x01, quality=1.0)

    hr, spo2 = store.get_fresh_values(300)

    assert hr == 76
    assert spo2 is None

    pipeline = object.__new__(StreamingPipeline)
    pipeline.health = store
    pipeline.data_stale_seconds = 300
    reply = pipeline._build_health_reply("心率和血氧")
    assert "心率 76" in reply
    assert "血氧 98" not in reply


def make_health_context_pipeline(store: HealthDataStore, stale_seconds: float = 60):
    pipeline = object.__new__(StreamingPipeline)
    pipeline.health = store
    pipeline.data_stale_seconds = stale_seconds
    return pipeline


def test_lightweight_health_context_contains_two_fresh_fields() -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=76, spo2=98, seq=1, flags=0x03, quality=1.0)
    clock.advance(8)

    context = make_health_context_pipeline(store)._build_lightweight_health_context()

    assert context is not None
    assert "心率 76（8秒前）" in context
    assert "血氧 98（8秒前）" in context


def test_lightweight_health_context_omits_independently_stale_field() -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=None, spo2=98, seq=1, flags=0x02, quality=1.0)
    clock.advance(61)
    store.update(hr=76, spo2=None, seq=2, flags=0x01, quality=1.0)

    context = make_health_context_pipeline(store)._build_lightweight_health_context()

    assert context is not None
    assert "心率 76（0秒前）" in context
    assert "血氧" not in context
    assert "98" not in context


def test_lightweight_health_context_is_none_when_all_fields_are_stale() -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=76, spo2=98, seq=1, flags=0x03, quality=1.0)
    clock.advance(61)

    context = make_health_context_pipeline(store)._build_lightweight_health_context()

    assert context is None


@pytest.mark.parametrize(
    ("flags", "quality"),
    [
        (0x03 | 0x04, 1.0),
        (0x03, 0.49),
    ],
)
def test_lightweight_health_context_never_exposes_rejected_frame(
    flags: int, quality: float
) -> None:
    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=150, spo2=88, seq=1, flags=flags, quality=quality)

    context = make_health_context_pipeline(store)._build_lightweight_health_context()

    assert context is None


def test_pipeline_binds_read_only_health_context_provider() -> None:
    class CapturingLightweight:
        def __init__(self):
            self.provider = None

        def set_health_context_provider(self, provider) -> None:
            self.provider = provider

    clock = FakeMonotonic()
    store = HealthDataStore(monotonic=clock)
    store.update(hr=76, spo2=98, seq=1, flags=0x03, quality=1.0)
    lightweight = CapturingLightweight()

    StreamingPipeline(
        asr=None,
        llm=None,
        tts=None,
        vad=None,
        lightweight_llm=lightweight,
        health=store,
        data_stale_seconds=60,
    )

    assert callable(lightweight.provider)
    assert "心率 76" in lightweight.provider()


def make_outbox(tmp_path, clock, ids, *, lease_seconds=30) -> AlertOutbox:
    return AlertOutbox(
        tmp_path / "alert_outbox.json",
        lease_seconds=lease_seconds,
        time_fn=clock,
        uuid_factory=ids,
    )


def test_tts_failure_before_lease_leaves_event_pending(tmp_path) -> None:
    clock = FakeMonotonic()
    outbox = make_outbox(tmp_path, clock, SequentialUUID())
    event = outbox.create_event(hr=140, spo2=93, quality=0.9, flags=0x03, seq=1)

    candidate = outbox.peek_for_box()
    assert candidate["id"] == event["id"]
    # TTS fails here: the route never calls lease_for_box.

    reloaded = make_outbox(tmp_path, clock, SequentialUUID())
    assert reloaded.peek_for_box()["id"] == event["id"]
    assert reloaded.get_event(event["id"])["box"]["status"] == "pending"


def test_expired_box_lease_is_redelivered(tmp_path) -> None:
    clock = FakeMonotonic()
    outbox = make_outbox(tmp_path, clock, SequentialUUID(), lease_seconds=30)
    event = outbox.create_event(hr=140, spo2=None, quality=1.0, flags=0x01, seq=2)
    assert outbox.lease_for_box(event["id"])["box"]["status"] == "leased"
    assert outbox.peek_for_box() is None

    clock.advance(31)

    assert outbox.release_expired_leases() == 1
    assert outbox.peek_for_box()["id"] == event["id"]


def test_duplicate_box_ack_is_idempotent_and_survives_restart(tmp_path) -> None:
    clock = FakeMonotonic()
    ids = SequentialUUID()
    outbox = make_outbox(tmp_path, clock, ids)
    event = outbox.create_event(hr=None, spo2=90, quality=1.0, flags=0x02, seq=3)
    outbox.lease_for_box(event["id"])

    assert outbox.acknowledge_box(event["id"])
    assert outbox.acknowledge_box(event["id"])

    reloaded = make_outbox(tmp_path, clock, ids)
    saved = reloaded.get_event(event["id"])
    assert saved["box"]["status"] == "acknowledged"
    assert reloaded.peek_for_box() is None


def test_restart_reloads_pending_event(tmp_path) -> None:
    clock = FakeMonotonic()
    ids = SequentialUUID()
    outbox = make_outbox(tmp_path, clock, ids)
    event = outbox.create_event(hr=145, spo2=None, quality=0.8, flags=0x01, seq=4)

    reloaded = make_outbox(tmp_path, clock, ids)

    assert reloaded.peek_for_box()["id"] == event["id"]


def test_outbox_atomic_file_is_bounded_by_count_and_retention(tmp_path) -> None:
    clock = FakeMonotonic()
    ids = SequentialUUID()
    state_file = tmp_path / "alert_outbox.json"
    outbox = AlertOutbox(
        state_file,
        max_events=2,
        retention_days=1,
        time_fn=clock,
        uuid_factory=ids,
    )
    first = outbox.create_event(hr=140, spo2=None, quality=1.0, flags=1, seq=1)
    outbox.create_event(hr=141, spo2=None, quality=1.0, flags=1, seq=2)
    third = outbox.create_event(hr=142, spo2=None, quality=1.0, flags=1, seq=3)
    assert outbox.get_event(first["id"]) is None
    assert outbox.get_event(third["id"]) is not None
    assert not list(tmp_path.glob("*.tmp"))

    clock.advance(86401)
    fourth = outbox.create_event(hr=143, spo2=None, quality=1.0, flags=1, seq=4)
    assert outbox.peek_for_box()["id"] == fourth["id"]


def test_persistent_abnormal_generates_new_event_after_cooldown() -> None:
    clock = FakeMonotonic()
    events: list[dict] = []
    store = HealthDataStore(
        alert_consecutive=1,
        alert_cooldown_s=10,
        alert_cb=events.append,
        monotonic=clock,
    )

    store.update(hr=140, spo2=None, seq=1, flags=0x01, quality=1.0)
    clock.advance(11)
    store.update(hr=141, spo2=None, seq=2, flags=0x01, quality=1.0)
    assert len(events) == 2

    store.update(hr=75, spo2=None, seq=3, flags=0x01, quality=1.0)
    store.update(hr=142, spo2=None, seq=4, flags=0x01, quality=1.0)
    assert len(events) == 3


class FailingTTS:
    async def synthesize(self, text: str) -> bytes:
        raise RuntimeError("synthetic TTS failure")


class SuccessfulTTS:
    async def synthesize(self, text: str) -> bytes:
        return b"RIFF" + b"\x00" * 40


def configure_alert_route(monkeypatch, outbox, tts) -> TestClient:
    monkeypatch.setattr(main, "alert_outbox", outbox, raising=False)
    monkeypatch.setattr(main, "tts", tts)
    monkeypatch.setattr(
        main.app.state,
        "device_auth",
        DeviceAuthState(token="test-device-token", mode="required"),
    )
    return TestClient(main.app)


def test_alert_route_tts_failure_does_not_create_lease(tmp_path, monkeypatch) -> None:
    clock = FakeMonotonic()
    outbox = make_outbox(tmp_path, clock, SequentialUUID())
    event = outbox.create_event(hr=140, spo2=None, quality=1.0, flags=0x01, seq=5)
    client = configure_alert_route(monkeypatch, outbox, FailingTTS())

    response = client.get(
        "/api/v1/health/alert",
        headers={"X-Device-Token": "test-device-token"},
    )

    assert response.status_code == 502
    assert outbox.get_event(event["id"])["box"]["status"] == "pending"


def test_alert_route_leases_then_acknowledges_idempotently(tmp_path, monkeypatch) -> None:
    clock = FakeMonotonic()
    outbox = make_outbox(tmp_path, clock, SequentialUUID())
    event = outbox.create_event(hr=140, spo2=92, quality=1.0, flags=0x03, seq=6)
    client = configure_alert_route(monkeypatch, outbox, SuccessfulTTS())
    headers = {"X-Device-Token": "test-device-token"}

    response = client.get("/api/v1/health/alert", headers=headers)

    assert response.status_code == 200
    assert response.headers["X-Alert-ID"] == event["id"]
    assert outbox.get_event(event["id"])["box"]["status"] == "leased"

    first_ack = client.post(f"/api/v1/health/alert/{event['id']}/ack", headers=headers)
    duplicate_ack = client.post(f"/api/v1/health/alert/{event['id']}/ack", headers=headers)
    assert first_ack.status_code == 200
    assert duplicate_ack.status_code == 200
    assert outbox.get_event(event["id"])["box"]["status"] == "acknowledged"


class FakeDateTime:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 30, 10, 0, 0)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class SequencedRunner:
    def __init__(self, returncodes: list[int]) -> None:
        self.returncodes = iter(returncodes)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(returncode=next(self.returncodes), stdout="", stderr="secret")


def test_wechat_sender_strips_proxy_environment(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:2")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.invalid:3")
    runner = SequencedRunner([0])
    pusher = WechatAlertPusher(
        chat_id="private-chat-id",
        runner=runner,
    )

    result = pusher.send(hr=80, spo2=98)

    assert result.success is True
    child_env = runner.calls[0][1]["env"]
    assert all(
        key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
        for key in child_env
    )


def test_wechat_failure_does_not_increment_and_success_persists(tmp_path) -> None:
    wall = FakeMonotonic()
    local_time = FakeDateTime()
    runner = SequencedRunner([1, 0])
    outbox = make_outbox(tmp_path, wall, SequentialUUID())
    event = outbox.create_event(hr=140, spo2=92, quality=1.0, flags=3, seq=7)
    pusher = WechatAlertPusher(
        chat_id="private-chat-id",
        daily_limit=5,
        state_file=tmp_path / "wechat_count.json",
        runner=runner,
        now_fn=local_time,
    )

    process_wechat_outbox_once(outbox, pusher, now_fn=wall)
    failed = outbox.get_event(event["id"])
    assert pusher.success_count == 0
    assert failed["wechat"]["status"] == "pending"
    assert failed["wechat"]["attempts"] == 1
    assert failed["wechat"]["next_retry_at"] > wall()

    wall.value = failed["wechat"]["next_retry_at"]
    process_wechat_outbox_once(outbox, pusher, now_fn=wall)
    assert pusher.success_count == 1
    assert outbox.get_event(event["id"])["wechat"]["status"] == "succeeded"

    reloaded_pusher = WechatAlertPusher(
        chat_id="private-chat-id",
        daily_limit=5,
        state_file=tmp_path / "wechat_count.json",
        runner=SequencedRunner([]),
        now_fn=local_time,
    )
    reloaded_outbox = make_outbox(tmp_path, wall, SequentialUUID())
    assert reloaded_pusher.success_count == 1
    assert reloaded_outbox.get_event(event["id"])["wechat"]["status"] == "succeeded"


def test_wechat_daily_limit_defers_event_to_next_local_day(tmp_path) -> None:
    wall = FakeMonotonic()
    local_time = FakeDateTime()
    runner = SequencedRunner([0])
    outbox = make_outbox(tmp_path, wall, SequentialUUID())
    first = outbox.create_event(hr=140, spo2=None, quality=1.0, flags=1, seq=8)
    second = outbox.create_event(hr=141, spo2=None, quality=1.0, flags=1, seq=9)
    pusher = WechatAlertPusher(
        chat_id="private-chat-id",
        daily_limit=1,
        state_file=tmp_path / "wechat_count.json",
        runner=runner,
        now_fn=local_time,
    )

    process_wechat_outbox_once(outbox, pusher, now_fn=wall)

    assert outbox.get_event(first["id"])["wechat"]["status"] == "succeeded"
    deferred = outbox.get_event(second["id"])
    assert deferred["wechat"]["status"] == "pending"
    assert deferred["wechat"]["last_error"] == "daily_limit"
    assert deferred["wechat"]["next_retry_at"] == pytest.approx(
        pusher.next_daily_reset_at()
    )
    assert len(runner.calls) == 1
