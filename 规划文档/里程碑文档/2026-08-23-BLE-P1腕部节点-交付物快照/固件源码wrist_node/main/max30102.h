#pragma once
#include <stdint.h>
#include "esp_err.h"

/* MAX30102 驱动（I2C 0x57，SpO2 模式 100Hz） */
#define MAX30102_I2C_ADDR 0x57

typedef struct {
    uint32_t red;   /* 18-bit 原始值 */
    uint32_t ir;
} max30102_sample_t;

esp_err_t max30102_init(void);
uint8_t   max30102_get_part_id(void);
int       max30102_read_fifo(max30102_sample_t *out, int max_samples);
