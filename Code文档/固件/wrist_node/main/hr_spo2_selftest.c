#include "hr_spo2.h"

#ifdef WRIST_SELF_TEST

#include <math.h>
#include <stdint.h>

#include "esp_err.h"
#include "esp_log.h"


#define TEST_SAMPLE_COUNT 1000
#define TEST_PERIOD_US 10000U
#define TWO_PI 6.28318530717958647692


esp_err_t hr_spo2_selftest(void)
{
    const char *tag = "hr_spo2_selftest";
    const uint32_t start_us = UINT32_MAX - 50000U;

    hr_spo2_test_reset();
    for (int i = 0; i < TEST_SAMPLE_COUNT; ++i) {
        double seconds = (double)i / 100.0;
        double wave = sin(TWO_PI * 1.25 * seconds);  /* literal 75 BPM */
        uint32_t ir = (uint32_t)(50000.0 + 5000.0 * wave);
        uint32_t red = (uint32_t)(45000.0 + 3000.0 * wave);
        hr_spo2_test_push_at(ir, red, start_us + (uint32_t)i * TEST_PERIOD_US);
    }
    (void)hr_spo2_compute();
    hr_spo2_result_t stable = hr_spo2_compute();
    if ((stable.flags & 0x01) == 0 || stable.heart_rate < 72 ||
        stable.heart_rate > 78) {
        ESP_LOGE(tag, "75 BPM vector failed hr=%u flags=0x%02x",
                 stable.heart_rate, stable.flags);
        return ESP_FAIL;
    }

    for (int i = 0; i < TEST_SAMPLE_COUNT; ++i) {
        uint32_t motion = (i == 100 || i == 350 || i == 700) ? 12000U : 0U;
        hr_spo2_test_push_at(50000U + motion, 45000U + motion / 2U,
                            start_us + (uint32_t)(TEST_SAMPLE_COUNT + i) *
                                           TEST_PERIOD_US);
    }
    hr_spo2_result_t noisy = hr_spo2_compute();
    if ((noisy.flags & 0x01) == 0 || (noisy.flags & 0x04) == 0 ||
        (noisy.flags & 0x02) != 0 || noisy.heart_rate != stable.heart_rate) {
        ESP_LOGE(tag,
                 "motion hold failed stable=%u noisy=%u flags=0x%02x",
                 stable.heart_rate, noisy.heart_rate, noisy.flags);
        return ESP_FAIL;
    }

    hr_spo2_test_reset();
    ESP_LOGI(tag, "PASS stable_hr=%u motion_flags=0x%02x",
             stable.heart_rate, noisy.flags);
    return ESP_OK;
}

#endif
