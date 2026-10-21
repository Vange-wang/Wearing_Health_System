#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BARGE_IN_GATE_WINDOW_FRAMES 20U
#define BARGE_IN_GATE_MIN_SPEECH_FRAMES 16U
#define BARGE_IN_GATE_MIN_TRAILING_SPEECH_FRAMES 8U

void barge_in_gate_init(void);
void barge_in_gate_reset(void);
bool barge_in_gate_process(bool vad_speech, uint64_t near_energy,
                           uint64_t noise_floor);

#ifdef __cplusplus
}
#endif
