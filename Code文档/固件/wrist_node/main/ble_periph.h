#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

/* BLE peripheral（NimBLE）：心率标准服务 + 血氧综合帧自定义服务 + 设备信息 */
esp_err_t ble_periph_init(void);
bool ble_is_connected(void);

/* 发送 8 字节综合帧 + 同步刷新标准心率特征 */
void ble_notify_frame(const uint8_t frame[8], uint8_t hr_bpm);
