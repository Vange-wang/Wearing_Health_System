#include "hr_spo2.h"
#include <math.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

/* ============================================================
 * HR/SpO2 算法 v2（自相关法，2026-08-23 深夜重写）
 *
 * 替代峰检测法的原因（真机实测证据链）：
 *   - 重搏切迹在峰检测中形成伪周期（HR 65↔172 二选一跳变），需不应期/切迹
 *     窗口等 6 重门限修补，仍反复横跳；
 *   - 自相关对切迹/噪声/节律性伪影天然免疫（离线 6 场景 5 个 ±3 BPM）。
 *
 * 设计：
 *   - 5 秒滑动窗口（样本数 = 5×实测速率，速率自适应）
 *   - HR：IR 通道自相关最强周期 → BPM；清晰度（归一化峰高）门控
 *   - SpO2：自相关峰幅值作 AC（AC²=2·ac[lag]），R 比率 + MAXREFDES117 拟合
 *   - 运动/低置信（清晰度低）：维持上一稳定值 + 伪影位（flags bit2）
 *   - 无手指：全部清空（防隔久复戴报旧值）
 *
 * 注意：ESP32-C3 无 FPU，自相关用 float（软件浮点 ~15-25ms/5s，可接受）。
 * ============================================================ */

/* 窗口时长（秒）：5s 全新窗口（每 5s 上报一帧，无重叠） */
#define WINDOW_SEC       5.0
/* 环缓冲容量（上限）：200Hz × 5s = 1000，1024 有余量 */
#define RING_SIZE        1024
/* 无手指判据：IR 直流分量低于此值（18-bit ADC） */
#define DC_MIN_VALID     8000
/* 心率搜索范围（BPM） */
#define BPM_MIN          40
#define BPM_MAX          200
/* 清晰度门限（归一化自相关峰高，0-1）：
 * 静置干净信号实测 ~0.8；重噪 ~0.4；运动 ~0.2。0.30 以下判低置信 */
#define CLARITY_VALID    0.30
/* 输出平滑：最近 3 个有效 BPM 取中位数 */
#define HR_SMOOTH_N      3

typedef struct {
    uint32_t ir[RING_SIZE];
    uint32_t red[RING_SIZE];
    uint32_t tstamp[RING_SIZE];   /* 入环时间（µs，仅窗口内差分用，回绕无影响） */
    int head;
    int count;
} ring_t;

static ring_t s_ring;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;

static uint16_t s_last_stable_hr = 0;
static uint16_t s_hr_hist[HR_SMOOTH_N];
static int s_hr_hist_n = 0;

void hr_spo2_push(uint32_t ir, uint32_t red)
{
    portENTER_CRITICAL(&s_mux);
    s_ring.ir[s_ring.head] = ir;
    s_ring.red[s_ring.head] = red;
    s_ring.tstamp[s_ring.head] = (uint32_t)esp_timer_get_time();
    s_ring.head = (s_ring.head + 1) % RING_SIZE;
    if (s_ring.count < RING_SIZE) {
        s_ring.count++;
    }
    portEXIT_CRITICAL(&s_mux);
}

/* 自相关求周期：x 先去趋势（一阶差分，滤直流漂移/接触松动电平跳变——实测
 * 0.4s 一次的直流平台跳变会在自相关形成强伪周期 0.2-0.3s，淹没真实心跳峰），
 * 再自相关搜索 [lag_lo, lag_hi] 最强周期。返回 (BPM, 清晰度)。 */
static void autocorr(const float *x, int n, float rate,
                     uint16_t *out_bpm, float *out_clarity)
{
    *out_bpm = 0;
    *out_clarity = 0.0f;
    if (n < 150) {   /* 至少 1.5s（@100Hz） */
        return;
    }

    /* 一阶差分（高通）：d[i] = x[i+1] - x[i]，滤直流电平跳变 */
    static float d[1024];
    for (int i = 0; i < n - 1; i++) {
        d[i] = x[i + 1] - x[i];
    }
    int m = n - 1;

    /* 去均值 */
    float mean = 0.0f;
    for (int i = 0; i < m; i++) {
        mean += d[i];
    }
    mean /= (float)m;

    /* ac[0] 归一化基准 */
    float ac0 = 0.0f;
    for (int i = 0; i < m; i++) {
        float v = d[i] - mean;
        ac0 += v * v;
    }
    if (ac0 < 1e-6f) {
        return;
    }

    int lo = (int)(60.0f / (float)BPM_MAX * rate);   /* 200 BPM → 0.30s */
    int hi = (int)(60.0f / (float)BPM_MIN * rate);   /* 40 BPM → 1.50s */
    if (lo < 8) lo = 8;
    if (hi > m / 2) hi = m / 2;
    if (lo >= hi) {
        return;
    }

    float best = -1.0f;
    int best_lag = lo;
    for (int lag = lo; lag <= hi; lag++) {
        float s = 0.0f;
        for (int i = 0; i + lag < m; i++) {
            s += (d[i] - mean) * (d[i + lag] - mean);
        }
        float v = s / ac0;
        if (v > best) {
            best = v;
            best_lag = lag;
        }
    }
    if (best <= 0.0f) {
        return;
    }
    *out_clarity = best;
    *out_bpm = (uint16_t)(60.0f * rate / (float)best_lag + 0.5f);
}

/* 自相关峰幅值（作 AC 用）：先一阶差分滤直流电平跳变，再 AC² = 2·mean(s) */
static float autocorr_ac(const float *x, int n, int lag)
{
    static float d[1024];
    for (int i = 0; i < n - 1; i++) {
        d[i] = x[i + 1] - x[i];
    }
    int m = n - 1;
    if (lag >= m) {
        return 0.0f;
    }

    float mean = 0.0f;
    for (int i = 0; i < m; i++) {
        mean += d[i];
    }
    mean /= (float)m;

    float s = 0.0f;
    for (int i = 0; i + lag < m; i++) {
        s += (d[i] - mean) * (d[i + lag] - mean);
    }
    if (s <= 0.0f) {
        return 0.0f;
    }
    return sqrtf(2.0f * s / (float)(m - lag));
}

hr_spo2_result_t hr_spo2_compute(void)
{
    hr_spo2_result_t r = { 0, 0, 0, 0 };

    /* 快照最近 n 个样本（临界区防采样任务写穿） */
    static float ir[RING_SIZE];
    static float red[RING_SIZE];
    static uint32_t tst[RING_SIZE];

    int n;
    portENTER_CRITICAL(&s_mux);
    n = s_ring.count;
    int start = (s_ring.head - n + RING_SIZE) % RING_SIZE;
    for (int i = 0; i < n; i++) {
        int idx = (start + i) % RING_SIZE;
        ir[i] = (float)s_ring.ir[idx];
        red[i] = (float)s_ring.red[idx];
        tst[i] = s_ring.tstamp[idx];
    }
    portEXIT_CRITICAL(&s_mux);

    if (n < 150) {
        return r;
    }

    /* 实测采样率（克隆芯片寄存器表可能与正品不符，必须以实测为准） */
    float rate = 100.0f;
    if (n >= 2 && tst[n - 1] > tst[0]) {
        rate = (float)(n - 1) * 1e6f / (float)(tst[n - 1] - tst[0]);
        if (rate < 5.0f || rate > 1000.0f) {
            rate = 100.0f;
        }
    }

    /* 5 秒窗口（样本数按实测速率） */
    int wn = (int)(WINDOW_SEC * rate);
    if (wn > n) wn = n;
    if (wn > RING_SIZE) wn = RING_SIZE;
    if (wn < 150) wn = (n < 150) ? n : 150;

    /* DC（窗口内均值） */
    double mean_ir = 0, mean_red = 0;
    for (int i = 0; i < wn; i++) {
        mean_ir += ir[i];
        mean_red += red[i];
    }
    mean_ir /= wn;
    mean_red /= wn;

    /* 手指在否 */
    if (mean_ir < DC_MIN_VALID) {
        s_last_stable_hr = 0;
        s_hr_hist_n = 0;
        ESP_LOGW("hr_spo2", "RAW n=%d irDC=%.0f（手指未检测到）", wn, mean_ir);
        return r;
    }

    /* ---- HR：IR 通道自相关 ---- */
    uint16_t bpm = 0;
    float clarity = 0.0f;
    autocorr(ir, wn, rate, &bpm, &clarity);

    bool hr_ok = (bpm >= BPM_MIN && bpm <= BPM_MAX && clarity >= CLARITY_VALID);
    uint16_t hr_out = 0;
    if (hr_ok) {
        /* 输出平滑：最近 3 个有效 BPM 中位数 */
        s_hr_hist[s_hr_hist_n % HR_SMOOTH_N] = bpm;
        s_hr_hist_n++;
        if (s_hr_hist_n >= HR_SMOOTH_N) {
            uint16_t t[HR_SMOOTH_N];
            for (int i = 0; i < HR_SMOOTH_N; i++) {
                t[i] = s_hr_hist[i];
            }
            for (int i = 0; i < HR_SMOOTH_N - 1; i++) {
                for (int j = i + 1; j < HR_SMOOTH_N; j++) {
                    if (t[j] < t[i]) {
                        uint16_t tmp = t[i]; t[i] = t[j]; t[j] = tmp;
                    }
                }
            }
            hr_out = t[HR_SMOOTH_N / 2];
        } else {
            hr_out = bpm;
        }
        s_last_stable_hr = hr_out;
    }

    /* ---- SpO2：自相关峰幅值作 AC（与 HR 同 lag） ---- */
    int lag = (int)(60.0f * rate / (float)(hr_ok ? bpm : (s_last_stable_hr > 0 ? s_last_stable_hr : 75)));
    float ac_ir = autocorr_ac(ir, wn, lag);
    float ac_red = autocorr_ac(red, wn, lag);
    float ratio_ir = (float)(ac_ir / mean_ir);
    float ratio_red = (float)(ac_red / mean_red);

    int spo2_valid = 0;
    float R = -1.0f;
    if (ratio_ir > 0.0001f && ratio_red > 0.0001f) {
        R = ratio_red / ratio_ir;
        if (R >= 0.4f && R <= 1.2f) {
            float spo2 = -45.060f * R * R + 30.354f * R + 94.845f;
            if (spo2 < 0) spo2 = 0;
            if (spo2 > 100) spo2 = 100;
            r.spo2 = (uint8_t)(spo2 + 0.5f);
            spo2_valid = 1;
        }
    }
    ESP_LOGI("hr_spo2", "RAW n=%d irDC=%.0f irAC=%.0f redDC=%.0f redAC=%.0f R=%.2f rate=%.0fHz",
             wn, mean_ir, (double)ac_ir, mean_red, (double)ac_red, (double)R, rate);

    /* ---- flags ---- */
    uint8_t flags = 0;
    if (hr_ok) {
        flags |= 0x01;
        r.heart_rate = hr_out;
    } else if (s_last_stable_hr > 0) {
        /* 低置信/运动：维持上一稳定值，标记伪影位 */
        flags |= 0x01 | 0x04;
        r.heart_rate = s_last_stable_hr;
    }
    if (spo2_valid && clarity >= CLARITY_VALID) {
        flags |= 0x02;
    }
    ESP_LOGW("diag", "bpm=%u clarity=%.2f R=%.2f hr_ok=%d spo2_ok=%d",
             bpm, (double)clarity, (double)R, hr_ok, spo2_valid);
    r.flags = flags;

    /* 调试转储（临时）：输出完整窗口 IR 样本（每 5 点一个，ir red 同行），
     * PC 端离线重建波形判断信号质量；联调完成后移除 */
    for (int i = 0; i < wn; i += 5) {
        ESP_LOGW("raw", "%.0f %.0f", (double)ir[i], (double)red[i]);
    }
    return r;
}
