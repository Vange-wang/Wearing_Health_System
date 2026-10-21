#include "barge_in_gate.h"

#include <string.h>

typedef struct {
    bool speech_history[BARGE_IN_GATE_WINDOW_FRAMES];
    uint8_t write_index;
    uint8_t frame_count;
    uint8_t speech_count;
    uint8_t trailing_speech_count;
} barge_in_gate_state_t;

static barge_in_gate_state_t s_state;

static bool has_near_energy_margin(uint64_t near_energy,
                                   uint64_t noise_floor)
{
    if (noise_floor == 0U || near_energy <= noise_floor) {
        return false;
    }

    const uint64_t required_margin =
        (noise_floor / 2U) + (noise_floor % 2U);
    return (near_energy - noise_floor) >= required_margin;
}

void barge_in_gate_init(void)
{
    barge_in_gate_reset();
}

void barge_in_gate_reset(void)
{
    memset(&s_state, 0, sizeof(s_state));
}

bool barge_in_gate_process(bool vad_speech, uint64_t near_energy,
                           uint64_t noise_floor)
{
    const bool is_speech =
        vad_speech && has_near_energy_margin(near_energy, noise_floor);

    if (s_state.frame_count == BARGE_IN_GATE_WINDOW_FRAMES) {
        if (s_state.speech_history[s_state.write_index]) {
            s_state.speech_count--;
        }
    } else {
        s_state.frame_count++;
    }

    s_state.speech_history[s_state.write_index] = is_speech;
    s_state.write_index =
        (uint8_t)((s_state.write_index + 1U) % BARGE_IN_GATE_WINDOW_FRAMES);

    if (is_speech) {
        s_state.speech_count++;
        s_state.trailing_speech_count++;
    } else {
        s_state.trailing_speech_count = 0U;
    }

    return s_state.speech_count >= BARGE_IN_GATE_MIN_SPEECH_FRAMES &&
           s_state.trailing_speech_count >=
               BARGE_IN_GATE_MIN_TRAILING_SPEECH_FRAMES;
}
