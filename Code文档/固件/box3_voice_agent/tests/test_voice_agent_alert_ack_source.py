from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "voice_agent" / "main" / "voice_agent.c"


def implementation() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_alert_id_is_read_and_validated_before_playback():
    source = implementation()

    assert "HTTP_EVENT_ON_HEADER" in source
    assert ".event_handler = alert_http_event" in source
    assert 'strcasecmp(event->header_key, "X-Alert-ID")' in source
    assert "esp_http_client_get_header" not in source
    assert "static bool valid_alert_id" in source
    assert "ALERT_ID_LENGTH" in source


def test_ack_is_sent_only_after_complete_uncancelled_playback():
    source = implementation()

    assert "static bool post_alert_ack" in source
    assert '"/ack"' in source
    assert "esp_http_client_is_complete_data_received(client)" in source
    assert "playback_complete" in source
    assert "if (playback_complete)" in source
    assert "post_alert_ack(alert_id)" in source
