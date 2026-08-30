#include "signal_diag.h"

#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

#define DIAG_LOG_INTERVAL_US 4000000LL

static signal_diag_snapshot_t s_snapshot;
static bool s_has_snapshot;
static int64_t s_last_log_us = -DIAG_LOG_INTERVAL_US;
static portMUX_TYPE s_diag_mux = portMUX_INITIALIZER_UNLOCKED;

void signal_diag_publish(const signal_diag_snapshot_t *snapshot)
{
    if (snapshot == NULL) {
        return;
    }

    portENTER_CRITICAL(&s_diag_mux);
    s_snapshot = *snapshot;
    s_has_snapshot = true;
    portEXIT_CRITICAL(&s_diag_mux);

    int64_t now_us = esp_timer_get_time();
    if (now_us - s_last_log_us < DIAG_LOG_INTERVAL_US) {
        return;
    }
    s_last_log_us = now_us;
    ESP_LOGI("signal_diag",
             "rate=%.1f dc_ir=%.0f dc_red=%.0f ac_ir=%.0f ac_red=%.0f "
             "band=%.3f quality=%.2f flags=0x%02x",
             snapshot->rate, snapshot->dc_ir, snapshot->dc_red,
             snapshot->ac_ir, snapshot->ac_red, snapshot->heart_band_ratio,
             snapshot->quality, snapshot->flags);
}

bool signal_diag_get_snapshot(signal_diag_snapshot_t *out)
{
    if (out == NULL) {
        return false;
    }
    portENTER_CRITICAL(&s_diag_mux);
    bool available = s_has_snapshot;
    if (available) {
        *out = s_snapshot;
    } else {
        memset(out, 0, sizeof(*out));
    }
    portEXIT_CRITICAL(&s_diag_mux);
    return available;
}
