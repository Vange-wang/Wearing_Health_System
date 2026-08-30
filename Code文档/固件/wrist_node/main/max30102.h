#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* MAX30102 驱动（I2C 0x57，SpO2 模式 100Hz） */
#define MAX30102_I2C_ADDR 0x57

typedef struct {
    uint32_t red;   /* 18-bit 原始值 */
    uint32_t ir;
} max30102_sample_t;

typedef struct {
    uint32_t transaction_errors;
    uint32_t fifo_overflows;
    uint32_t recovery_attempts;
    uint32_t recovery_failures;
    uint32_t consecutive_failures;
} max30102_stats_t;

esp_err_t max30102_init(void);
esp_err_t max30102_recover(void);
uint8_t   max30102_get_part_id(void);
int       max30102_read_fifo(max30102_sample_t *out, int max_samples);
void      max30102_get_stats(max30102_stats_t *out);
bool      max30102_take_window_invalidated(void);

#ifdef MAX30102_SELF_TEST
esp_err_t max30102_fault_injection_selftest(void);
#endif
