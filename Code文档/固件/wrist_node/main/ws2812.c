#include "ws2812.h"
#include "driver/rmt_tx.h"
#include "driver/gpio.h"
#include "esp_log.h"

static const char *TAG = "ws2812";

#define PIN_LED GPIO_NUM_8

/* 80MHz RMT 时钟（12.5ns/tick）：0 码 = 0.4µs 高 + 0.8µs 低；1 码 = 0.8µs 高 + 0.4µs 低 */
#define BIT0_H_TICKS 32
#define BIT0_L_TICKS 64
#define BIT1_H_TICKS 64
#define BIT1_L_TICKS 32

static rmt_channel_handle_t s_tx_chan = NULL;
static rmt_encoder_handle_t s_copy_encoder = NULL;
static rmt_symbol_word_t s_symbols[24];

esp_err_t ws2812_init(void)
{
    rmt_tx_channel_config_t tx_cfg = {
        .gpio_num = PIN_LED,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 80 * 1000 * 1000,
        .mem_block_symbols = 64,
        .trans_queue_depth = 4,
        .intr_priority = 0,
    };
    esp_err_t err = rmt_new_tx_channel(&tx_cfg, &s_tx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "RMT 通道创建失败: %s", esp_err_to_name(err));
        return err;
    }

    rmt_copy_encoder_config_t copy_cfg = {};
    err = rmt_new_copy_encoder(&copy_cfg, &s_copy_encoder);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "copy 编码器创建失败: %s", esp_err_to_name(err));
        return err;
    }

    err = rmt_enable(s_tx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "RMT 使能失败: %s", esp_err_to_name(err));
        return err;
    }
    return ESP_OK;
}

void ws2812_set_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    if (s_tx_chan == NULL) {
        return;
    }
    /* WS2812B 数据序 GRB */
    uint32_t color = ((uint32_t)g << 16) | ((uint32_t)r << 8) | (uint32_t)b;
    for (int i = 0; i < 24; i++) {
        bool bit = (color >> (23 - i)) & 1;
        s_symbols[i].duration0 = bit ? BIT1_H_TICKS : BIT0_H_TICKS;
        s_symbols[i].level0 = 1;
        s_symbols[i].duration1 = bit ? BIT1_L_TICKS : BIT0_L_TICKS;
        s_symbols[i].level1 = 0;
    }
    rmt_transmit_config_t tx_conf = {
        .loop_count = 0,
    };
    rmt_transmit(s_tx_chan, s_copy_encoder, s_symbols, sizeof(s_symbols), &tx_conf);
    rmt_tx_wait_all_done(s_tx_chan, 20);
}
