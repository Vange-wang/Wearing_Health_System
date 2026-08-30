from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "examples" / "voice_agent" / "main"


def source() -> str:
    return (MAIN / "ble_central.c").read_text(encoding="utf-8")


def test_cccd_write_is_two_byte_little_endian_and_checks_completion():
    implementation = source()

    assert "uint8_t cccd_val[2] = {0x01, 0x00};" in implementation
    assert "sizeof(cccd_val), cccd_write_cb" in implementation
    assert "CCCD 写入完成" in implementation


def test_descriptor_discovery_uses_service_end_handle():
    implementation = source()

    assert "s_combo_svc_end_handle = service->end_handle" in implementation
    assert "s_combo_svc_end_handle," in implementation
    assert "chr->val_handle + 1" not in implementation


def test_peer_address_type_is_persisted_and_reused():
    implementation = source()

    assert '#define NVS_KEY_ADDR "peer_addr"' in implementation
    assert "static ble_addr_t s_peer_addr" in implementation
    assert "s_peer_addr = event->disc.addr" in implementation
    assert "start_connect(&s_peer_addr)" in implementation


def test_advertisement_requires_hr_and_spo2_capabilities():
    implementation = source()

    assert "(capabilities & TARGET_MFG_CAPS) == TARGET_MFG_CAPS" in implementation


def test_disconnect_invalidates_cache_and_next_frame_rebases_sequence():
    implementation = source()

    assert "static void invalidate_cache(void)" in implementation
    assert "invalidate_cache();" in implementation
    assert "if (health->valid)" in implementation
    assert "h.lost = health->lost" in implementation


def test_health_uploader_transmits_protocol_flags_and_quality():
    implementation = source()

    assert '\\"flags\\":%u' in implementation
    assert '\\"quality\\":%.2f' in implementation
    assert "h->conf > 100 ? 100 : h->conf" in implementation
    assert '\\"hr\\":null,\\"spo2\\":null' in implementation
    assert "if (s_upload_sem)" in implementation
    assert "!ble_central_get_data(&h))" in implementation
