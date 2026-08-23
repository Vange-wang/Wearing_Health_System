#include "hr_spo2.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

/* 滑动窗口（样本数）：名义 100Hz 下 ≈10s，实际时长随实测速率自适应 */
#define WINDOW_SIZE    1024
/* 无手指判据：IR 直流分量低于此值（18-bit ADC） */
#define DC_MIN_VALID   8000
/* 峰最小间距（秒）：0.3s → 心率上限 200 BPM，按实测速率换算成样本数 */
#define PEAK_MIN_DIST_SEC 0.3

typedef struct {
    uint32_t ir[WINDOW_SIZE];
    uint32_t red[WINDOW_SIZE];
    uint32_t tstamp[WINDOW_SIZE];   /* 入环时间（µs，仅窗口内差分用，回绕无影响） */
    int head;
    int count;
} ring_t;

static ring_t s_ring;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;

void hr_spo2_push(uint32_t ir, uint32_t red)
{
    portENTER_CRITICAL(&s_mux);
    s_ring.ir[s_ring.head] = ir;
    s_ring.red[s_ring.head] = red;
    s_ring.tstamp[s_ring.head] = (uint32_t)esp_timer_get_time();
    s_ring.head = (s_ring.head + 1) % WINDOW_SIZE;
    if (s_ring.count < WINDOW_SIZE) {
        s_ring.count++;
    }
    portEXIT_CRITICAL(&s_mux);
}

static int cmp_u32(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a;
    uint32_t y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

hr_spo2_result_t hr_spo2_compute(void)
{
    hr_spo2_result_t r = { 0, 0, 0, 0 };

    /* 快照最近 n 个样本（临界区防采样任务写穿） */
    static uint32_t ir[WINDOW_SIZE];
    static uint32_t red[WINDOW_SIZE];
    static uint32_t tst[WINDOW_SIZE];
    static double   smooth[WINDOW_SIZE];

    int n;
    portENTER_CRITICAL(&s_mux);
    n = s_ring.count;
    int start = (s_ring.head - n + WINDOW_SIZE) % WINDOW_SIZE;
    for (int i = 0; i < n; i++) {
        int idx = (start + i) % WINDOW_SIZE;
        ir[i] = s_ring.ir[idx];
        red[i] = s_ring.red[idx];
        tst[i] = s_ring.tstamp[idx];
    }
    portEXIT_CRITICAL(&s_mux);

    if (n < 100) {   /* 至少 1s 数据 */
        return r;
    }

    /* 实测采样率（克隆芯片寄存器表可能与正品不符，必须以实测为准） */
    double rate = 100.0;   /* 兜底默认 */
    if (n >= 2 && tst[n - 1] > tst[0]) {
        rate = (double)(n - 1) * 1e6 / (double)(tst[n - 1] - tst[0]);
        if (rate < 5.0 || rate > 1000.0) {
            rate = 100.0;
        }
    }
    int min_dist = (int)(rate * PEAK_MIN_DIST_SEC);
    if (min_dist < 5) min_dist = 5;
    if (min_dist > 300) min_dist = 300;

    /* DC / AC（标准差） */
    double mean_ir = 0, mean_red = 0;
    for (int i = 0; i < n; i++) {
        mean_ir += (double)ir[i];
        mean_red += (double)red[i];
    }
    mean_ir /= n;
    mean_red /= n;

    double var_ir = 0, var_red = 0;
    for (int i = 0; i < n; i++) {
        double d = (double)ir[i] - mean_ir;
        var_ir += d * d;
        d = (double)red[i] - mean_red;
        var_red += d * d;
    }
    var_ir /= n;
    var_red /= n;
    double ac_ir = sqrt(var_ir);
    double ac_red = sqrt(var_red);

    /* 手指在否 */
    if (mean_ir < DC_MIN_VALID) {
        ESP_LOGW("hr_spo2", "RAW n=%d irDC=%d irAC=%d redDC=%d redAC=%d（手指未检测到）",
                 n, (int)mean_ir, (int)ac_ir, (int)mean_red, (int)ac_red);
        return r;   /* 全无效 */
    }

    /* ---- SpO2：R 比率（MAXREFDES117 二次拟合） ---- */
    double ratio_ir = ac_ir / mean_ir;
    double ratio_red = ac_red / mean_red;
    ESP_LOGI("hr_spo2", "RAW n=%d irDC=%d irAC=%d redDC=%d redAC=%d R=%.2f rate=%.0fHz",
             n, (int)mean_ir, (int)ac_ir, (int)mean_red, (int)ac_red,
             (ratio_ir > 0.0005) ? (ratio_red / ratio_ir) : -1.0, rate);
    int spo2_valid = 0;
    if (ratio_ir > 0.0005 && ratio_red > 0.0005) {
        double R = ratio_red / ratio_ir;
        if (R >= 0.4 && R <= 3.0) {
            double spo2 = -45.060 * R * R + 30.354 * R + 94.845;
            if (spo2 < 0) spo2 = 0;
            if (spo2 > 100) spo2 = 100;
            r.spo2 = (uint8_t)(spo2 + 0.5);
            spo2_valid = 1;
        }
    }

    /* ---- HR：IR 5 点滑动平滑 + 峰检测 ---- */
    for (int i = 2; i < n - 2; i++) {
        smooth[i] = ((double)ir[i - 2] + ir[i - 1] + ir[i] + ir[i + 1] + ir[i + 2]) / 5.0;
    }
    double thr = mean_ir + 0.5 * ac_ir;

    static uint32_t peaks[64];
    int npeaks = 0;
    int last_peak = -min_dist * 2;
    for (int i = 1; i < n - 1; i++) {
        if (smooth[i] > thr &&
            smooth[i] >= smooth[i - 1] &&
            smooth[i] > smooth[i + 1]) {
            if (i - last_peak >= min_dist) {
                peaks[npeaks] = (uint32_t)i;
                if (npeaks < 63) npeaks++;
                last_peak = i;
            }
        }
    }

    uint16_t bpm = 0;
    double cv = 1.0;   /* 峰间期变异系数（默认差） */
    if (npeaks >= 2) {
        static uint32_t intervals[64];
        int nin = npeaks - 1;
        for (int j = 0; j < nin; j++) {
            intervals[j] = peaks[j + 1] - peaks[j];
        }
        qsort(intervals, (size_t)nin, sizeof(uint32_t), cmp_u32);
        uint32_t median = intervals[nin / 2];
        if (median > 0) {
            bpm = (uint16_t)(60.0 * rate / median + 0.5);   /* 按实测速率换算 BPM */
        }
        /* 离散度 */
        double m = 0;
        for (int j = 0; j < nin; j++) m += (double)intervals[j];
        m /= nin;
        double v = 0;
        for (int j = 0; j < nin; j++) {
            double d = (double)intervals[j] - m;
            v += d * d;
        }
        v /= nin;
        if (m > 0) cv = sqrt(v) / m;
    }

    /* ---- 置信度 ---- */
    int conf = 0;
    if (npeaks >= 5) conf += 60;
    else if (npeaks >= 3) conf += 40;
    else if (npeaks >= 2) conf += 20;
    if (npeaks >= 4) {
        if (cv < 0.10) conf += 35;
        else if (cv < 0.20) conf += 25;
        else if (cv < 0.35) conf += 10;
    }
    if (conf > 100) conf = 100;
    r.confidence = (uint8_t)conf;

    /* ---- flags ---- */
    uint8_t flags = 0;
    if (npeaks >= 4 && bpm >= 30 && bpm <= 220) {
        flags |= 0x01;
        r.heart_rate = bpm;
    }
    if (spo2_valid) {
        flags |= 0x02;
    }
    if (conf < 60) {
        flags |= 0x04;   /* 运动伪影/低置信 */
    }
    r.flags = flags;
    return r;
}
