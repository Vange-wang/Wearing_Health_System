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
/* 峰最小间距（不应期，自适应，2026-08-23 微动修复）：
 * - 基准 0.30s（心率上限 200 BPM，不设低上限）
 * - 锁定稳定 HR 后拉长到 0.5×上一RR、封顶 0.45s（静息期滤除重搏切迹：
 *   6mA 下切迹 300-400ms 次峰曾致 HR 二选一跳变 65vs172）
 * - 连续低峰数逃生：静息信号下峰数持续低于预期一半 → 放宽 0.30s 重新冷启动
 *   （真实心率快速上升时不应期会挡死新节律，必须能自我解锁） */
static double s_refract_s = 0.30;
#define REFRACT_BASE_S   0.30
#define REFRACT_MAX_S    0.45
#define REFRACT_RR_FRAC  0.5
/* 低峰数判定：静息信号（AC/DC < 1.2%，运动期 AC/DC 达 1.5-5% 不误判） */
#define QUIET_AC_RATIO   0.012
/* 切迹抑制窗口（秒）：近距离双峰保留更高者——重搏切迹矮于主峰，运动伪影
 * 第二峰可能更高（同样被保留）。窗口自适应 0.55×上一RR（锁定后随心率收缩，
 * 高心率不设墙），未锁定默认 0.45s（放置期即可滤切迹，冷启动首锁落在真实心率）。 */
static double s_notch_win_s = 0.45;
#define NOTCH_WIN_DEFAULT 0.45
#define NOTCH_WIN_RR_FRAC 0.55
#define NOTCH_WIN_MIN     0.30
#define NOTCH_WIN_MAX     0.50
/* 噪声底扣除（SpO2 用）：弱脉动时红通道噪声底淹没真实 AC → R 虚高假低。
   取最近 N 窗口的 AC 最小值作噪声底估计（运动窗口 AC 巨大不影响最小值）。 */
#define AC_FLOOR_WIN 12
static double s_ir_ac_hist[AC_FLOOR_WIN];
static double s_red_ac_hist[AC_FLOOR_WIN];
static int s_ac_hist_n = 0;
static int s_ac_hist_i = 0;
/* 峰高阈值系数（相对 AC 幅度，2026-08-23 微动修复）：过滤运动伪影小伪峰 */
#define PEAK_THR_AC       0.7
/* qcd 有效性门限（四分位离散度，实测标定：静置 0.18-0.53 / 运动 0.56-1.68） */
#define QCD_VALID_MAX     0.50
/* 变化率门限：相对上一稳定值跳变超 30% 需 qcd≤0.10（极规整）才接受 */
#define HR_CHANGE_FRAC    0.30
#define QCD_STRICT        0.10
/* 输出平滑：最近 3 个有效 BPM 取中位数 */
#define HR_SMOOTH_N       3

/* 上一稳定 HR（文件级：无手指时重置，运动期维持上报） */
static uint16_t s_last_stable_hr = 0;
static uint16_t s_hr_hist[HR_SMOOTH_N];
static int s_hr_hist_n = 0;
/* 冷启动一致性：上一合格窗口 bpm + 连续一致计数（防手指刚放的节律性运动伪影被锁定） */
static uint16_t s_last_ok_bpm = 0;
static int s_cold_agree = 0;
/* 低峰数逃生计数（不应期放宽用） */
static int s_low_peaks = 0;
/* 分歧共识（2026-08-23）：连续合格窗口互相一致但与锁定值差异大 → 强制重锁，
   堵错误锁定自维持（128 假锁后真实 73 被变化率门限长期阻挡） */
static uint16_t s_dissent_bpm = 0;
static int s_dissent_agree = 0;
/* 冷启动：连续 3 个合格窗口且相互一致（±20 bpm）才锁定。
 * 2026-08-23 实测：放置瞬态的节律性动作可维持 10-15s，2 窗口一致性会被骗过
 * （147→163 假锁定），3 窗口（~15s 静置）显著提高锁假门槛。 */
#define COLD_AGREE_BPM  20

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
    int min_dist = (int)(rate * s_refract_s);
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
        s_last_stable_hr = 0;   /* 无手指：清上一稳定值，防隔久复戴报旧值 */
        s_hr_hist_n = 0;
        s_last_ok_bpm = 0;
        s_cold_agree = 0;
        s_dissent_bpm = 0;
        s_dissent_agree = 0;
        s_notch_win_s = NOTCH_WIN_DEFAULT;   /* 无手指重置切迹窗口 */
        ESP_LOGW("hr_spo2", "RAW n=%d irDC=%d irAC=%d redDC=%d redAC=%d（手指未检测到）",
                 n, (int)mean_ir, (int)ac_ir, (int)mean_red, (int)ac_red);
        return r;   /* 全无效 */
    }

    /* ---- SpO2：R 比率（MAXREFDES117 二次拟合），AC 先扣噪声底 ---- */
    /* 噪声底 = 最近 AC_FLOOR_WIN 窗口的 AC 最小值（仅手指在位时更新） */
    if (s_ac_hist_n < AC_FLOOR_WIN) {
        s_ir_ac_hist[s_ac_hist_i] = ac_ir;
        s_red_ac_hist[s_ac_hist_i] = ac_red;
        s_ac_hist_i++;
        s_ac_hist_n++;
    } else {
        s_ir_ac_hist[s_ac_hist_i] = ac_ir;
        s_red_ac_hist[s_ac_hist_i] = ac_red;
        s_ac_hist_i = (s_ac_hist_i + 1) % AC_FLOOR_WIN;
    }
    double floor_ir = 1e9, floor_red = 1e9;
    for (int i = 0; i < s_ac_hist_n; i++) {
        if (s_ir_ac_hist[i] < floor_ir) floor_ir = s_ir_ac_hist[i];
        if (s_red_ac_hist[i] < floor_red) floor_red = s_red_ac_hist[i];
    }
    double ac_ir_c = ac_ir - floor_ir;
    double ac_red_c = ac_red - floor_red;
    if (ac_ir_c < 0) ac_ir_c = 0;
    if (ac_red_c < 0) ac_red_c = 0;

    double ratio_ir = ac_ir_c / mean_ir;
    double ratio_red = ac_red_c / mean_red;
    ESP_LOGI("hr_spo2", "RAW n=%d irDC=%d irAC=%d redDC=%d redAC=%d R=%.2f rate=%.0fHz",
             n, (int)mean_ir, (int)ac_ir, (int)mean_red, (int)ac_red,
             (ratio_ir > 0.0005) ? (ratio_red / ratio_ir) : -1.0, rate);
    int spo2_valid = 0;
    if (ratio_ir > 0.001 && ratio_red > 0.001) {
        double R = ratio_red / ratio_ir;
        /* R 比率上限 1.2（2026-08-23 修正）：健康人 R∈[0.4,1.0]；R>1.2 对应
           SpO2<85，静息时出现即接触伪影（实测假低 76 由此混入）。MAXREFDES117
           拟合本身只标定 90-100 区间，1.2 封顶牺牲 <85 的极端低值报告，
           换取消除日常假低误报。 */
        if (R >= 0.4 && R <= 1.2) {
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
    /* 峰高阈值（相对 AC）：低于此高度的局部极大判为微动伪峰 */
    double thr = mean_ir + PEAK_THR_AC * ac_ir;

    static uint32_t peaks[64];
    int npeaks = 0;
    int last_peak_idx = -1000;
    int notch_dist = (int)(rate * s_notch_win_s);
    for (int i = 1; i < n - 1; i++) {
        if (smooth[i] > thr &&
            smooth[i] >= smooth[i - 1] &&
            smooth[i] > smooth[i + 1]) {
            int gap = i - last_peak_idx;
            if (gap >= min_dist) {
                if (gap < notch_dist && npeaks > 0 &&
                    smooth[i] > smooth[last_peak_idx]) {
                    /* 切迹抑制：近距双峰保留更高者（前一峰是切迹 → 替换） */
                    peaks[npeaks - 1] = (uint32_t)i;
                    last_peak_idx = i;
                } else if (gap >= notch_dist || smooth[i] <= smooth[last_peak_idx]) {
                    if (gap < notch_dist) {
                        /* 近距矮峰 = 切迹，丢弃 */
                    } else {
                        peaks[npeaks] = (uint32_t)i;
                        if (npeaks < 63) npeaks++;
                        last_peak_idx = i;
                    }
                }
            }
            /* gap < min_dist：不应期，丢弃 */
        }
    }

    /* 低峰数逃生：静息信号（AC/DC < 1.2%）下峰数持续显著低于预期 →
     * 不应期可能挡死了真实心率上升，放宽并重新冷启动（不丢失运动期维持值） */
    {
        double ac_ratio = ac_ir / mean_ir;
        double win_sec = (double)n / rate;
        double expect = win_sec * (s_last_stable_hr > 0 ? (double)s_last_stable_hr : 70.0) / 60.0;
        if (ac_ratio < QUIET_AC_RATIO && expect > 0 && npeaks < expect * 0.5) {
            s_low_peaks++;
        } else {
            s_low_peaks = 0;
        }
        if (s_low_peaks >= 2) {
            s_refract_s = REFRACT_BASE_S;
            s_last_stable_hr = 0;
            s_hr_hist_n = 0;
            s_last_ok_bpm = 0;
            s_cold_agree = 0;
            s_low_peaks = 0;
            ESP_LOGW("hr_spo2", "不应期放宽（连续低峰数，可能心率已上升）");
        }
    }

    uint16_t bpm = 0;
    double cv = 1.0;   /* 峰间期变异系数（默认差） */
    double qcd = 1.0;  /* 四分位离散度（对孤立野点鲁棒） */
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
        if (nin >= 3 && median > 0) {
            qcd = (double)(intervals[(3 * nin) / 4] - intervals[nin / 4]) / (double)median;
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

    /* ---- HR 有效性判定（2026-08-23 微动修复，阈值由实测诊断数据标定）----
     * 三重门限：
     *   1. qcd（四分位离散度）≤ 0.45：静置帧实测 0.18-0.38，运动帧 0.56-1.68，判别力最强；
     *   2. 变化率门限：相对上一稳定值跳变 >30% 且 qcd>0.10 → 判运动伪影
     *      （堵节律规整的运动伪影，实测漏网案例：qcd=0.19 的 bpm=140 假跳）；
     *   3. 输出中位数平滑（3 帧）+ 运动期维持上一稳定值 + 置伪影位（flags bit2）。 */
    bool hr_ok = (npeaks >= 4 && bpm >= 30 && bpm <= 220 && qcd <= QCD_VALID_MAX);
    if (hr_ok && s_last_stable_hr > 0) {
        uint16_t diff = (bpm > s_last_stable_hr) ? (bpm - s_last_stable_hr)
                                                 : (s_last_stable_hr - bpm);
        if ((double)diff > HR_CHANGE_FRAC * (double)s_last_stable_hr) {
            /* 大跳变：默认拒绝（运动伪影）；但连续 3 个合格窗口互相一致
               （分歧共识）→ 强制重锁——堵错误锁定自维持（128 假锁后真实
               73 长期被挡；qcd≤0.10 极规整单窗口仍可直接接受） */
            if (s_dissent_bpm > 0) {
                uint16_t dd = (bpm > s_dissent_bpm) ? (bpm - s_dissent_bpm)
                                                    : (s_dissent_bpm - bpm);
                if (dd <= COLD_AGREE_BPM) {
                    s_dissent_agree++;
                } else {
                    s_dissent_agree = 0;
                }
            }
            s_dissent_bpm = bpm;
            if (qcd <= QCD_STRICT || s_dissent_agree >= 2) {
                hr_ok = true;
                s_dissent_agree = 0;
                s_hr_hist_n = 0;   /* 重锁：清平滑历史，防旧值污染中位数 */
                ESP_LOGW("hr_spo2", "分歧共识重锁 bpm=%u", bpm);
            } else {
                hr_ok = false;
            }
        } else {
            s_dissent_agree = 0;
            s_dissent_bpm = 0;
        }
    }
    if (hr_ok && s_last_stable_hr == 0) {
        /* 冷启动：连续 2 个合格窗口且相互一致（±15 bpm）才锁定，
           防手指刚放上时节律规整的运动伪影（实测 qcd=0.12 的 bpm=188 假锁定） */
        if (s_last_ok_bpm > 0) {
            uint16_t diff = (bpm > s_last_ok_bpm) ? (bpm - s_last_ok_bpm)
                                                  : (s_last_ok_bpm - bpm);
            if (diff <= COLD_AGREE_BPM) {
                s_cold_agree++;
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
        /* 输出平滑：最近 3 个有效 BPM 中位数（防单帧抖动） */
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
            hr_out = bpm;   /* 平滑窗口未满，先直接报 */
        }
        s_last_stable_hr = hr_out;
        /* 自适应不应期：0.5×上一RR，封顶 0.45s、下限 0.30s（下一窗口生效） */
        double rr = 60.0 / (double)hr_out;
        double new_refract = REFRACT_RR_FRAC * rr;
        if (new_refract > REFRACT_MAX_S) new_refract = REFRACT_MAX_S;
        if (new_refract < REFRACT_BASE_S) new_refract = REFRACT_BASE_S;
        s_refract_s = new_refract;
        /* 切迹抑制窗口同源自适应：0.55×上一RR，钳位 [0.30, 0.50] */
        double nw = NOTCH_WIN_RR_FRAC * rr;
        if (nw > NOTCH_WIN_MAX) nw = NOTCH_WIN_MAX;
        if (nw < NOTCH_WIN_MIN) nw = NOTCH_WIN_MIN;
        s_notch_win_s = nw;
    }

    /* ---- flags ---- */
    uint8_t flags = 0;
    if (hr_ok) {
        flags |= 0x01;
        r.heart_rate = hr_out;
    } else if (s_last_stable_hr > 0) {
        /* 运动伪影期（含 npeaks=0 的剧烈运动）：维持上一稳定值，标记伪影位 */
        flags |= 0x01 | 0x04;
        r.heart_rate = s_last_stable_hr;
        if (conf > 40) {
            conf = 40;
            r.confidence = (uint8_t)conf;
        }
    }
    if (spo2_valid && npeaks >= 4 && qcd <= QCD_VALID_MAX) {
        /* SpO2 门控（2026-08-23 修正）：按单窗口信号质量判定，不依赖 HR 锁定——
         * 冷启动期/HR 未锁定但信号干净时 SpO2 也应上报（此前与 hr_ok 绑定，
         * 导致 HR 未锁定时问血氧无回答）；运动期 qcd 超限同样拦截（R 比率失真假低） */
        flags |= 0x02;
    }
    if (conf < 60) {
        flags |= 0x04;   /* 运动伪影/低置信 */
    }
    ESP_LOGW("diag", "npeaks=%d bpm=%u cv=%.2f qcd=%.2f hr_ok=%d", npeaks, bpm, cv, qcd, hr_ok);
    r.flags = flags;
    return r;
}
