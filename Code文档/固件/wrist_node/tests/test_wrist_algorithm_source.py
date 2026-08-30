from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "examples" / "ble_wrist_node" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text(encoding="utf-8")


def test_e2_four_threshold_peak_detector_and_complete_recent_window_are_production_path():
    algorithm = read("hr_spo2.c")

    assert "WINDOW_SECONDS 10.0" in algorithm
    assert "PEAK_MIN_DIST_SEC 0.45" in algorithm
    assert "PEAK_THR_AC 0.7" in algorithm
    assert "QCD_VALID_MAX 0.50" in algorithm
    assert "HR_CHANGE_FRAC 0.30" in algorithm
    assert "COLD_AGREE_BPM 20" in algorithm
    assert "smooth[i] > threshold" in algorithm
    assert "qsort(intervals" in algorithm
    assert "autocorr(" not in algorithm
    assert "int offset = available - needed" in algorithm


def test_timestamp_rate_is_wrap_safe_and_invalid_rate_has_no_fake_fallback():
    algorithm = read("hr_spo2.c")

    assert "(uint32_t)(timestamps[available - 1] - timestamps[0])" in algorithm
    assert "rate = 100" not in algorithm
    assert "rate < MIN_RATE_HZ || rate > MAX_RATE_HZ" in algorithm


def test_diagnostics_are_bounded_and_raw_samples_are_opt_in():
    algorithm = read("hr_spo2.c")
    diag_header = read("signal_diag.h")
    diag_source = read("signal_diag.c")

    for field in (
        "rate",
        "dc_ir",
        "dc_red",
        "ac_ir",
        "ac_red",
        "heart_band_ratio",
        "quality",
        "flags",
    ):
        assert field in diag_header
    assert "DIAG_LOG_INTERVAL_US" in diag_source
    assert "#ifdef WRIST_DIAG_RAW" in algorithm
    assert "WRIST_DIAG_RAW" not in read("CMakeLists.txt")


def test_ble_frame_layout_is_unchanged_and_production_selftest_is_disabled():
    main = read("main.c")
    cmake = read("CMakeLists.txt")

    assert "uint8_t frame[8]" in main
    assert "frame[0] = seq++" in main
    assert "frame[1] = r.flags" in main
    assert "frame[2] = (uint8_t)(r.heart_rate & 0xFF)" in main
    assert "frame[7] = 0" in main
    assert "WRIST_SELF_TEST" not in cmake


def test_wrist_build_uses_utf8_and_propagates_failure_status():
    build_script = (ROOT / "build_wrist.py").read_text(encoding="utf-8")

    assert 'env["PYTHONUTF8"] = "1"' in build_script
    assert 'env["PYTHONIOENCODING"] = "utf-8"' in build_script
    assert "raise SystemExit(r.returncode)" in build_script
