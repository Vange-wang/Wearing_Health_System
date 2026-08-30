from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "examples" / "ble_wrist_node" / "main"


def read(name: str) -> str:
    return (MAIN / name).read_text(encoding="utf-8")


def test_sampling_register_values_match_pre_task_table():
    driver = read("max30102.c")

    expected = {
        "LED_CURRENT": "0x17",
        "FIFO_CONFIG_VALUE": "0x0F",
        "SPO2_CONFIG_VALUE": "0x26",
        "MLED_CTRL1_VALUE": "0x21",
        "SPO2_MODE_VALUE": "0x03",
    }
    for name, value in expected.items():
        assert f"#define {name}" in driver
        definition = next(line for line in driver.splitlines() if line.startswith(f"#define {name}"))
        assert definition.split()[-1] == value


def test_success_resets_consecutive_failures_and_config_errors_propagate():
    driver = read("max30102.c")

    assert "if (ok) {\n        s_consec_fails = 0;" in driver
    assert "++s_stats.transaction_errors" in driver
    assert "configure_sensor(write_reg)" in driver
    assert "if (err != ESP_OK) {\n        return err;" in driver
    assert "初始化完成" in driver


def test_overflow_is_checked_before_pointer_math_and_invalidates_algorithm():
    driver = read("max30102.c")
    main = read("main.c")

    overflow_read = driver.index("read_reg(REG_OVF_COUNTER")
    pointer_read = driver.index("read_reg(REG_FIFO_RD_PTR", overflow_read)
    assert overflow_read < pointer_read
    assert "handle_fifo_overflow(overflow, read_regs, write_reg)" in driver
    assert "s_window_invalidated = true" in driver
    assert "max30102_take_window_invalidated()" in main
    assert "hr_spo2_invalidate_window()" in main


def test_recovery_and_fault_injection_paths_are_observable():
    driver = read("max30102.c")
    header = read("max30102.h")

    assert "esp_err_t max30102_recover(void)" in driver
    assert "recovery_attempts" in header
    assert "recovery_failures" in header
    assert "max30102_fault_injection_selftest" in driver
    assert "configure_sensor(selftest_writer) == ESP_OK" in driver
    assert "recover_with_writer(selftest_writer, false) == ESP_OK" in driver
    assert "handle_fifo_overflow(1, selftest_reader, selftest_writer)" in driver


def test_main_checks_subsystem_and_task_results_without_led_becoming_fatal():
    main = read("main.c")

    assert "NVS 初始化失败" in main
    assert "s_led_ready = (ret == ESP_OK)" in main
    assert "传感与 BLE 继续运行" in main
    assert "esp_err_t ble_ret = ble_periph_init()" in main
    assert main.count("xTaskCreate(") == 3
    assert main.count("!= pdPASS") == 3


def test_production_fault_injection_is_disabled():
    assert "MAX30102_SELF_TEST" not in read("CMakeLists.txt")
