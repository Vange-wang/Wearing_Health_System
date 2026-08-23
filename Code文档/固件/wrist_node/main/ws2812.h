#pragma once
#include <stdint.h>
#include "esp_err.h"

/* WS2812B RGB 状态灯（GPIO8，RMT 驱动） */
esp_err_t ws2812_init(void);
void ws2812_set_rgb(uint8_t r, uint8_t g, uint8_t b);
