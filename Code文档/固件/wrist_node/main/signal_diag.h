#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    float rate;
    float dc_ir;
    float dc_red;
    float ac_ir;
    float ac_red;
    float heart_band_ratio;
    float quality;
    uint8_t flags;
} signal_diag_snapshot_t;

void signal_diag_publish(const signal_diag_snapshot_t *snapshot);
bool signal_diag_get_snapshot(signal_diag_snapshot_t *out);
