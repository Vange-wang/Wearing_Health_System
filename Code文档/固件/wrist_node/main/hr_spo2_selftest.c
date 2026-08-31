#include "hr_spo2.h"

#ifdef WRIST_SELF_TEST

#include <math.h>
#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "esp_log.h"


#define TEST_SAMPLE_COUNT 1000
#define TEST_PERIOD_US 10000U
#define TWO_PI 6.28318530717958647692
#define TEST_PULSE_WIDTH_SEC 0.035
#define TEST_TRUE_PERIOD_SEC 1.0
#define TEST_SECONDARY_DELAY_SEC 0.55
#define TEST_IR_DC 50000.0
#define TEST_RED_DC 45000.0


static double periodic_pulse(double seconds, double period_seconds,
                             double phase_seconds)
{
    double distance = fmod(seconds - phase_seconds, period_seconds);
    if (distance < 0.0) {
        distance += period_seconds;
    }
    if (distance > period_seconds / 2.0) {
        distance -= period_seconds;
    }
    double normalized = distance / TEST_PULSE_WIDTH_SEC;
    return exp(-0.5 * normalized * normalized);
}

static uint32_t rounded_sample(double value)
{
    if (value <= 0.0) {
        return 0;
    }
    if (value >= (double)UINT32_MAX) {
        return UINT32_MAX;
    }
    return (uint32_t)(value + 0.5);
}

static void feed_periodic_vector(uint32_t start_us, int count,
                                 double period_seconds, double red_amplitude)
{
    for (int i = 0; i < count; ++i) {
        double seconds = (double)i / 100.0;
        double pulse = periodic_pulse(seconds, period_seconds, 0.0);
        uint32_t ir = rounded_sample(TEST_IR_DC + 6000.0 * pulse);
        uint32_t red = rounded_sample(TEST_RED_DC + red_amplitude * pulse);
        hr_spo2_test_push_at(ir, red,
                             start_us + (uint32_t)i * TEST_PERIOD_US);
    }
}

static double jittered_pulse_train(double seconds)
{
    static const double intervals[] = {
        0.90, 0.90, 0.95, 1.05, 1.05, 0.95,
    };
    double pulse = 0.0;
    double event_seconds = 0.0;
    for (int i = 0; i < 16; ++i) {
        double distance = seconds - event_seconds;
        double normalized = distance / TEST_PULSE_WIDTH_SEC;
        pulse += exp(-0.5 * normalized * normalized);
        event_seconds += intervals[i % (int)(sizeof(intervals) /
                                               sizeof(intervals[0]))];
    }
    return pulse;
}

static void feed_jittered_vector(uint32_t start_us, int count)
{
    for (int i = 0; i < count; ++i) {
        double seconds = (double)i / 100.0;
        double pulse = jittered_pulse_train(seconds);
        uint32_t ir = rounded_sample(TEST_IR_DC + 6000.0 * pulse);
        uint32_t red = rounded_sample(TEST_RED_DC + 3000.0 * pulse);
        hr_spo2_test_push_at(ir, red,
                             start_us + (uint32_t)i * TEST_PERIOD_US);
    }
}

static void feed_secondary_peak_vector(uint32_t start_us, int count,
                                       bool mismatched_red)
{
    for (int i = 0; i < count; ++i) {
        double seconds = (double)i / 100.0;
        double primary = periodic_pulse(seconds, TEST_TRUE_PERIOD_SEC, 0.0);
        double secondary = periodic_pulse(seconds, TEST_TRUE_PERIOD_SEC,
                                          TEST_SECONDARY_DELAY_SEC);
        uint32_t ir = rounded_sample(TEST_IR_DC + 6000.0 * primary +
                                     3000.0 * secondary);
        double red_wave;
        if (mismatched_red) {
            /* R is deliberately in the legacy formula's accepted range, but
             * RED morphology is not time-aligned with the IR pulse train. */
            red_wave = 6500.0 *
                       periodic_pulse(seconds, TEST_TRUE_PERIOD_SEC, 0.25);
        } else {
            red_wave = 3000.0 * primary + 1500.0 * secondary;
        }
        uint32_t red = rounded_sample(TEST_RED_DC + red_wave);
        hr_spo2_test_push_at(ir, red,
                             start_us + (uint32_t)i * TEST_PERIOD_US);
    }
}

static esp_err_t check_secondary_peak_rejection(const char *tag)
{
    hr_spo2_test_reset();
    feed_secondary_peak_vector(0U, TEST_SAMPLE_COUNT, false);
    hr_spo2_result_t first = hr_spo2_compute();
    hr_spo2_result_t second = hr_spo2_compute();
    hr_spo2_result_t third = hr_spo2_compute();

    if ((first.flags & 0x01) != 0 ||
        ((second.flags & 0x01) != 0 && second.heart_rate > 80) ||
        (third.flags & 0x01) == 0 || third.heart_rate < 58 ||
        third.heart_rate > 66) {
        ESP_LOGE(tag,
                 "secondary peak rejection failed first=%u/0x%02x "
                 "second=%u/0x%02x third=%u/0x%02x",
                 first.heart_rate, first.flags, second.heart_rate,
                 second.flags, third.heart_rate, third.flags);
        return ESP_FAIL;
    }
    ESP_LOGI(tag,
             "secondary rejection first=%u/0x%02x second=%u/0x%02x "
             "third=%u/0x%02x",
             first.heart_rate, first.flags, second.heart_rate, second.flags,
             third.heart_rate, third.flags);
    return ESP_OK;
}

static esp_err_t check_bounded_recovery(const char *tag)
{
    hr_spo2_test_reset();
    feed_periodic_vector(0U, TEST_SAMPLE_COUNT, 0.60, 3000.0);
    (void)hr_spo2_compute();
    hr_spo2_result_t locked = hr_spo2_compute();
    if ((locked.flags & 0x01) == 0 || locked.heart_rate < 95 ||
        locked.heart_rate > 105) {
        ESP_LOGE(tag, "recovery setup failed locked=%u flags=0x%02x",
                 locked.heart_rate, locked.flags);
        return ESP_FAIL;
    }

    feed_jittered_vector(10000000U, TEST_SAMPLE_COUNT);
    hr_spo2_result_t first_true_window = hr_spo2_compute();
    feed_jittered_vector(20000000U, TEST_SAMPLE_COUNT);
    hr_spo2_result_t recovered = hr_spo2_compute();

    if ((recovered.flags & 0x01) == 0 || recovered.heart_rate < 60 ||
        recovered.heart_rate > 66 ||
        (((first_true_window.flags & 0x01) != 0) &&
         first_true_window.heart_rate > 80 &&
         (first_true_window.flags & 0x04) == 0)) {
        ESP_LOGE(tag,
                 "bounded recovery failed first=%u/0x%02x recovered=%u/0x%02x",
                 first_true_window.heart_rate, first_true_window.flags,
                 recovered.heart_rate, recovered.flags);
        return ESP_FAIL;
    }
    ESP_LOGI(tag, "bounded recovery first=%u/0x%02x recovered=%u/0x%02x",
             first_true_window.heart_rate, first_true_window.flags,
             recovered.heart_rate, recovered.flags);
    return ESP_OK;
}

static esp_err_t check_spo2_quality_gate(const char *tag)
{
    hr_spo2_test_reset();
    feed_secondary_peak_vector(0U, TEST_SAMPLE_COUNT, true);
    (void)hr_spo2_compute();
    (void)hr_spo2_compute();
    hr_spo2_result_t bad = hr_spo2_compute();

    if ((bad.flags & 0x02) != 0 || bad.spo2 != 0 ||
        (bad.flags & 0x03) == 0x03) {
        ESP_LOGE(tag, "SpO2 quality gate failed spo2=%u flags=0x%02x",
                 bad.spo2, bad.flags);
        return ESP_FAIL;
    }
    ESP_LOGI(tag, "SpO2 rejection spo2=%u flags=0x%02x", bad.spo2,
             bad.flags);
    return ESP_OK;
}

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
        stable.heart_rate > 78 || (stable.flags & 0x02) == 0 ||
        stable.spo2 == 0) {
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

    if (check_secondary_peak_rejection(tag) != ESP_OK ||
        check_bounded_recovery(tag) != ESP_OK ||
        check_spo2_quality_gate(tag) != ESP_OK) {
        return ESP_FAIL;
    }

    hr_spo2_test_reset();
    ESP_LOGI(tag, "PASS stable_hr=%u motion_flags=0x%02x",
             stable.heart_rate, noisy.flags);
    return ESP_OK;
}

#endif
