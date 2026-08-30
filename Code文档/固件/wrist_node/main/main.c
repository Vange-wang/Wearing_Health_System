/**
 * ble_wrist_node —— P1 腕部节点固件
 *
 * ESP32-C3 SuperMini + MAX30102（I2C GPIO4/GPIO5）：
 *  - SpO2 模式采集（名义 100Hz，算法按实测速率自适应，克隆芯片寄存器表可能不准）
 *  - 10s 滑动窗口计算心率/血氧/置信度
 *  - 每 5s 通过 BLE notify 发 8 字节综合帧（协议 2026-08-19-BLE数据帧协议）
 *  - 同时刷新标准心率服务 0x180D/0x2A37（手机工具直连调试用）
 *  - GPIO8 WS2812B：未连接红色 / 已连接绿色呼吸
 */
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "max30102.h"
#include "hr_spo2.h"
#include "ble_periph.h"
#include "ws2812.h"

#ifdef WRIST_SELF_TEST
esp_err_t hr_spo2_selftest(void);
#endif
#ifdef MAX30102_SELF_TEST
esp_err_t max30102_selftest(void);
#endif

static const char *TAG = "wrist";
static bool s_led_ready;

#define SAMPLE_TASK_PERIOD_MS 10   /* FIFO 轮询周期（100Hz 采样，10ms 不溢出） */
#define REPORT_PERIOD_MS      5000 /* 5s/帧 */

static void sample_task(void *arg)
{
    max30102_sample_t samples[32];
    uint32_t total = 0, prev_total = 0;
    int64_t last_log = 0;
    while (1) {
        int n = max30102_read_fifo(samples, sizeof(samples) / sizeof(samples[0]));
        if (max30102_take_window_invalidated()) {
            hr_spo2_invalidate_window();
            ESP_LOGW(TAG, "算法窗口因 FIFO overflow 已作废");
        }
        total += n;
        for (int i = 0; i < n; i++) {
            hr_spo2_push(samples[i].ir, samples[i].red);
        }
        int64_t now = esp_timer_get_time();
        if (now - last_log > 5000000) {
            double hz = (now > last_log) ?
                (double)(total - prev_total) * 1e6 / (double)(now - last_log) : 0.0;
            prev_total = total;
            last_log = now;
            ESP_LOGW("sample", "累计 %lu 样本（近 5s +%d，≈%.0f Hz），last ir=%lu red=%lu",
                     total, n, hz, n > 0 ? samples[n - 1].ir : 0UL, n > 0 ? samples[n - 1].red : 0UL);
        }
        vTaskDelay(pdMS_TO_TICKS(SAMPLE_TASK_PERIOD_MS));
    }
}

static void led_task(void *arg)
{
    while (1) {
        if (ble_is_connected()) {
            /* 绿色呼吸 */
            double t = (double)esp_timer_get_time() / 1000.0;
            double b = 0.5 + 0.5 * sin(t / 600.0);
            uint8_t g = (uint8_t)(25 + 150 * b);
            ws2812_set_rgb(0, g, 0);
        } else {
            /* 红色常亮（未连接） */
            ws2812_set_rgb(40, 0, 0);
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

static void report_task(void *arg)
{
    uint8_t seq = 0;
    while (1) {
        hr_spo2_result_t r = hr_spo2_compute();

        uint8_t frame[8];
        frame[0] = seq++;                  /* 帧序号，回绕 */
        frame[1] = r.flags;                /* bit0 HR bit1 SpO2 bit2 伪影 */
        frame[2] = (uint8_t)(r.heart_rate & 0xFF);
        frame[3] = (uint8_t)((r.heart_rate >> 8) & 0xFF);
        frame[4] = r.spo2;
        frame[5] = r.confidence;
        frame[6] = 100;                    /* P1 USB 供电 */
        frame[7] = 0;

        if (ble_is_connected()) {
            ble_notify_frame(frame, (uint8_t)r.heart_rate);
        }

        ESP_LOGI(TAG, "HR=%u SpO2=%u conf=%u flags=0x%02x seq=%u",
                 r.heart_rate, r.spo2, r.confidence, r.flags, frame[0]);
        vTaskDelay(pdMS_TO_TICKS(REPORT_PERIOD_MS));
    }
}

void app_main(void)
{
#ifdef WRIST_SELF_TEST
    ESP_ERROR_CHECK(hr_spo2_selftest());
#endif
#ifdef MAX30102_SELF_TEST
    ESP_ERROR_CHECK(max30102_selftest());
#endif
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ret = nvs_flash_erase();
        if (ret == ESP_OK) {
            ret = nvs_flash_init();
        }
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "NVS 初始化失败: %s", esp_err_to_name(ret));
        return;
    }

    ret = ws2812_init();
    s_led_ready = (ret == ESP_OK);
    if (s_led_ready) {
        ws2812_set_rgb(40, 0, 0);
    } else {
        ESP_LOGW(TAG, "WS2812 初始化失败，传感与 BLE 继续运行: %s",
                 esp_err_to_name(ret));
    }

    ret = max30102_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "MAX30102 初始化失败: %s（红灯快闪，每 2s 重试）", esp_err_to_name(ret));
        while (1) {
            if (s_led_ready) ws2812_set_rgb(120, 0, 0);
            vTaskDelay(pdMS_TO_TICKS(200));
            if (s_led_ready) ws2812_set_rgb(0, 0, 0);
            vTaskDelay(pdMS_TO_TICKS(1800));
            ret = max30102_init();
            if (ret == ESP_OK) {
                break;
            }
            ESP_LOGE(TAG, "MAX30102 重试失败: %s", esp_err_to_name(ret));
        }
    }

    esp_err_t ble_ret = ble_periph_init();
    if (ble_ret != ESP_OK) {
        ESP_LOGE(TAG, "BLE 初始化失败，进入可见降级状态: %s",
                 esp_err_to_name(ble_ret));
    }
    ESP_LOGI(TAG, "腕部节点就绪：广播 %s，5s/帧", "WH-Wrist01");

    if (xTaskCreate(sample_task, "sample", 4096, NULL, 6, NULL) != pdPASS) {
        ESP_LOGE(TAG, "sample task 创建失败");
    }
    if (xTaskCreate(report_task, "report", 4096, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "report task 创建失败");
    }
    if (s_led_ready &&
        xTaskCreate(led_task, "led", 3072, NULL, 4, NULL) != pdPASS) {
        ESP_LOGW(TAG, "LED task 创建失败，传感与 BLE 继续运行");
    }
}
