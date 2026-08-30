#include "hr_spo2.h"

#include <math.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "signal_diag.h"

#define WINDOW_SIZE 1024
#define WINDOW_SECONDS 10.0
#define DC_MIN_VALID 8000
#define PEAK_MIN_DIST_SEC 0.45
#define PEAK_THR_AC 0.7
#define QCD_VALID_MAX 0.50
#define HR_CHANGE_FRAC 0.30
#define QCD_STRICT 0.10
#define HR_SMOOTH_N 3
#define COLD_AGREE_BPM 20
#define MIN_RATE_HZ 5.0
#define MAX_RATE_HZ 1000.0

typedef struct {
    uint32_t ir[WINDOW_SIZE];
    uint32_t red[WINDOW_SIZE];
    uint32_t tstamp[WINDOW_SIZE];
    int head;
    int count;
} ring_t;

static ring_t s_ring;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static uint16_t s_last_stable_hr;
static uint16_t s_hr_hist[HR_SMOOTH_N];
static int s_hr_hist_n;
static uint16_t s_last_ok_bpm;
static int s_cold_agree;

static void reset_tracking_state(void)
{
    s_last_stable_hr = 0;
    memset(s_hr_hist, 0, sizeof(s_hr_hist));
    s_hr_hist_n = 0;
    s_last_ok_bpm = 0;
    s_cold_agree = 0;
}

static void push_at(uint32_t ir, uint32_t red, uint32_t timestamp_us)
{
    portENTER_CRITICAL(&s_mux);
    s_ring.ir[s_ring.head] = ir;
    s_ring.red[s_ring.head] = red;
    s_ring.tstamp[s_ring.head] = timestamp_us;
    s_ring.head = (s_ring.head + 1) % WINDOW_SIZE;
    if (s_ring.count < WINDOW_SIZE) {
        s_ring.count++;
    }
    portEXIT_CRITICAL(&s_mux);
}

void hr_spo2_push(uint32_t ir, uint32_t red)
{
    push_at(ir, red, (uint32_t)esp_timer_get_time());
}

void hr_spo2_invalidate_window(void)
{
    portENTER_CRITICAL(&s_mux);
    memset(&s_ring, 0, sizeof(s_ring));
    reset_tracking_state();
    portEXIT_CRITICAL(&s_mux);
}

#ifdef WRIST_SELF_TEST
void hr_spo2_test_reset(void)
{
    hr_spo2_invalidate_window();
}

void hr_spo2_test_push_at(uint32_t ir, uint32_t red, uint32_t timestamp_us)
{
    push_at(ir, red, timestamp_us);
}
#endif

static int cmp_u32(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a;
    uint32_t y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

static float periodicity_at_lag(const uint32_t *samples, int n,
                                double mean, uint32_t lag)
{
    if (lag == 0 || lag >= (uint32_t)n) {
        return 0.0f;
    }
    double cross = 0.0;
    double energy_a = 0.0;
    double energy_b = 0.0;
    for (int i = 0; i + (int)lag < n; ++i) {
        double a = (double)samples[i] - mean;
        double b = (double)samples[i + lag] - mean;
        cross += a * b;
        energy_a += a * a;
        energy_b += b * b;
    }
    if (energy_a <= 0.0 || energy_b <= 0.0) {
        return 0.0f;
    }
    double ratio = cross / sqrt(energy_a * energy_b);
    if (ratio < 0.0) ratio = 0.0;
    if (ratio > 1.0) ratio = 1.0;
    return (float)ratio;
}

static void publish_diag(float rate, double dc_ir, double dc_red,
                         double ac_ir, double ac_red, float band_ratio,
                         float quality, uint8_t flags)
{
    signal_diag_snapshot_t snapshot = {
        .rate = rate,
        .dc_ir = (float)dc_ir,
        .dc_red = (float)dc_red,
        .ac_ir = (float)ac_ir,
        .ac_red = (float)ac_red,
        .heart_band_ratio = band_ratio,
        .quality = quality,
        .flags = flags,
    };
    signal_diag_publish(&snapshot);
}

hr_spo2_result_t hr_spo2_compute(void)
{
    hr_spo2_result_t result = { 0, 0, 0, 0 };
    static uint32_t ir[WINDOW_SIZE];
    static uint32_t red[WINDOW_SIZE];
    static uint32_t timestamps[WINDOW_SIZE];
    static double smooth[WINDOW_SIZE];

    int available;
    portENTER_CRITICAL(&s_mux);
    available = s_ring.count;
    int start = (s_ring.head - available + WINDOW_SIZE) % WINDOW_SIZE;
    for (int i = 0; i < available; ++i) {
        int index = (start + i) % WINDOW_SIZE;
        ir[i] = s_ring.ir[index];
        red[i] = s_ring.red[index];
        timestamps[i] = s_ring.tstamp[index];
    }
    portEXIT_CRITICAL(&s_mux);

    if (available < 2) {
        publish_diag(0.0f, 0.0, 0.0, 0.0, 0.0, 0.0f, 0.0f, 0);
        return result;
    }

    uint32_t elapsed_us = (uint32_t)(timestamps[available - 1] - timestamps[0]);
    if (elapsed_us == 0) {
        result.flags = 0x04;
        publish_diag(0.0f, 0.0, 0.0, 0.0, 0.0, 0.0f, 0.0f,
                     result.flags);
        return result;
    }
    double rate = (double)(available - 1) * 1000000.0 / (double)elapsed_us;
    if (rate < MIN_RATE_HZ || rate > MAX_RATE_HZ) {
        result.flags = 0x04;
        publish_diag((float)rate, 0.0, 0.0, 0.0, 0.0, 0.0f, 0.0f,
                     result.flags);
        return result;
    }

    int needed = (int)(WINDOW_SECONDS * rate + 0.5);
    if (needed < 100 || needed > WINDOW_SIZE || available < needed) {
        publish_diag((float)rate, 0.0, 0.0, 0.0, 0.0, 0.0f, 0.0f, 0);
        return result;
    }

    int offset = available - needed;
    const uint32_t *window_ir = &ir[offset];
    const uint32_t *window_red = &red[offset];
    int n = needed;

    double mean_ir = 0.0;
    double mean_red = 0.0;
    for (int i = 0; i < n; ++i) {
        mean_ir += (double)window_ir[i];
        mean_red += (double)window_red[i];
    }
    mean_ir /= n;
    mean_red /= n;

    double var_ir = 0.0;
    double var_red = 0.0;
    for (int i = 0; i < n; ++i) {
        double delta = (double)window_ir[i] - mean_ir;
        var_ir += delta * delta;
        delta = (double)window_red[i] - mean_red;
        var_red += delta * delta;
    }
    var_ir /= n;
    var_red /= n;
    double ac_ir = sqrt(var_ir);
    double ac_red = sqrt(var_red);

    if (mean_ir < DC_MIN_VALID) {
        reset_tracking_state();
        publish_diag((float)rate, mean_ir, mean_red, ac_ir, ac_red,
                     0.0f, 0.0f, 0);
        return result;
    }

    int spo2_valid = 0;
    double ratio_ir = ac_ir / mean_ir;
    double ratio_red = ac_red / mean_red;
    if (ratio_ir > 0.0005 && ratio_red > 0.0005) {
        double ratio = ratio_red / ratio_ir;
        if (ratio >= 0.4 && ratio <= 3.0) {
            double spo2 = -45.060 * ratio * ratio + 30.354 * ratio + 94.845;
            if (spo2 < 0.0) spo2 = 0.0;
            if (spo2 > 100.0) spo2 = 100.0;
            result.spo2 = (uint8_t)(spo2 + 0.5);
            spo2_valid = 1;
        }
    }

    for (int i = 0; i < n; ++i) {
        smooth[i] = (double)window_ir[i];
    }
    for (int i = 2; i < n - 2; ++i) {
        smooth[i] = ((double)window_ir[i - 2] + window_ir[i - 1] +
                     window_ir[i] + window_ir[i + 1] + window_ir[i + 2]) / 5.0;
    }

    int min_distance = (int)(rate * PEAK_MIN_DIST_SEC);
    if (min_distance < 5) min_distance = 5;
    if (min_distance > 300) min_distance = 300;
    double threshold = mean_ir + PEAK_THR_AC * ac_ir;

    static uint32_t peaks[64];
    int peak_count = 0;
    int last_peak = -min_distance * 2;
    for (int i = 1; i < n - 1; ++i) {
        if (smooth[i] > threshold && smooth[i] >= smooth[i - 1] &&
            smooth[i] > smooth[i + 1] && i - last_peak >= min_distance) {
            peaks[peak_count] = (uint32_t)i;
            if (peak_count < 63) {
                ++peak_count;
            }
            last_peak = i;
        }
    }

    uint16_t bpm = 0;
    double interval_cv = 1.0;
    double qcd = 1.0;
    uint32_t median_interval = 0;
    if (peak_count >= 2) {
        static uint32_t intervals[64];
        int interval_count = peak_count - 1;
        for (int i = 0; i < interval_count; ++i) {
            intervals[i] = peaks[i + 1] - peaks[i];
        }
        qsort(intervals, (size_t)interval_count, sizeof(uint32_t), cmp_u32);
        median_interval = intervals[interval_count / 2];
        if (median_interval > 0) {
            bpm = (uint16_t)(60.0 * rate / (double)median_interval + 0.5);
        }
        if (interval_count >= 3 && median_interval > 0) {
            qcd = (double)(intervals[(3 * interval_count) / 4] -
                                    intervals[interval_count / 4]) /
                  (double)median_interval;
        }

        double mean_interval = 0.0;
        for (int i = 0; i < interval_count; ++i) {
            mean_interval += (double)intervals[i];
        }
        mean_interval /= interval_count;
        double interval_variance = 0.0;
        for (int i = 0; i < interval_count; ++i) {
            double delta = (double)intervals[i] - mean_interval;
            interval_variance += delta * delta;
        }
        interval_variance /= interval_count;
        if (mean_interval > 0.0) {
            interval_cv = sqrt(interval_variance) / mean_interval;
        }
    }

    int confidence = 0;
    if (peak_count >= 5) confidence += 60;
    else if (peak_count >= 3) confidence += 40;
    else if (peak_count >= 2) confidence += 20;
    if (peak_count >= 4) {
        if (interval_cv < 0.10) confidence += 35;
        else if (interval_cv < 0.20) confidence += 25;
        else if (interval_cv < 0.35) confidence += 10;
    }
    if (confidence > 100) confidence = 100;
    result.confidence = (uint8_t)confidence;

    bool hr_ok = (peak_count >= 4 && bpm >= 30 && bpm <= 220 &&
                  qcd <= QCD_VALID_MAX);
    if (hr_ok && s_last_stable_hr > 0) {
        uint16_t difference = (bpm > s_last_stable_hr)
                                  ? (bpm - s_last_stable_hr)
                                  : (s_last_stable_hr - bpm);
        if ((double)difference >
                HR_CHANGE_FRAC * (double)s_last_stable_hr &&
            qcd > QCD_STRICT) {
            hr_ok = false;
        }
    }
    if (hr_ok && s_last_stable_hr == 0) {
        if (s_last_ok_bpm > 0) {
            uint16_t difference = (bpm > s_last_ok_bpm)
                                      ? (bpm - s_last_ok_bpm)
                                      : (s_last_ok_bpm - bpm);
            if (difference <= COLD_AGREE_BPM) {
                ++s_cold_agree;
            } else {
                s_cold_agree = 0;
            }
        }
        s_last_ok_bpm = bpm;
        if (s_cold_agree < 1) {
            hr_ok = false;
        }
    }

    uint16_t hr_out = 0;
    if (hr_ok) {
        s_hr_hist[s_hr_hist_n % HR_SMOOTH_N] = bpm;
        ++s_hr_hist_n;
        if (s_hr_hist_n >= HR_SMOOTH_N) {
            uint16_t sorted[HR_SMOOTH_N];
            memcpy(sorted, s_hr_hist, sizeof(sorted));
            for (int i = 0; i < HR_SMOOTH_N - 1; ++i) {
                for (int j = i + 1; j < HR_SMOOTH_N; ++j) {
                    if (sorted[j] < sorted[i]) {
                        uint16_t temporary = sorted[i];
                        sorted[i] = sorted[j];
                        sorted[j] = temporary;
                    }
                }
            }
            hr_out = sorted[HR_SMOOTH_N / 2];
        } else {
            hr_out = bpm;
        }
        s_last_stable_hr = hr_out;
    }

    if (hr_ok) {
        result.flags |= 0x01;
        result.heart_rate = hr_out;
    } else if (s_last_stable_hr > 0) {
        result.flags |= 0x01 | 0x04;
        result.heart_rate = s_last_stable_hr;
        if (confidence > 40) {
            confidence = 40;
            result.confidence = (uint8_t)confidence;
        }
    }
    if (spo2_valid && hr_ok) {
        result.flags |= 0x02;
    }
    if (confidence < 60) {
        result.flags |= 0x04;
    }

    float heart_band_ratio = periodicity_at_lag(window_ir, n, mean_ir,
                                                 median_interval);
    publish_diag((float)rate, mean_ir, mean_red, ac_ir, ac_red,
                 heart_band_ratio, (float)confidence / 100.0f, result.flags);

#ifdef WRIST_DIAG_RAW
    for (int i = 0; i < n; i += 5) {
        ESP_LOGW("wrist_raw", "%lu %lu",
                 (unsigned long)window_ir[i], (unsigned long)window_red[i]);
    }
#endif

    return result;
}
