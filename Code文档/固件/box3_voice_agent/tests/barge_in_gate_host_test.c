#include "barge_in_gate.h"

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

static const uint64_t kNearEnergy = 1000U;
static const uint64_t kNoiseFloor = 100U;

static void test_exactly_sixteen_speech_frames_in_twenty_triggers(void)
{
    barge_in_gate_init();

    for (size_t i = 0; i < 4U; ++i) {
        assert(!barge_in_gate_process(false, kNearEnergy, kNoiseFloor));
    }
    for (size_t i = 0; i < 16U; ++i) {
        assert(barge_in_gate_process(true, kNearEnergy, kNoiseFloor) ==
               (i == 15U));
    }

    barge_in_gate_reset();
}

static void test_single_frame_spike_does_not_trigger(void)
{
    barge_in_gate_reset();

    assert(!barge_in_gate_process(true, kNearEnergy, kNoiseFloor));
    for (size_t i = 1U; i < 20U; ++i) {
        assert(!barge_in_gate_process(false, kNearEnergy, kNoiseFloor));
    }
}

static void test_seven_frame_short_sound_does_not_trigger(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 7U; ++i) {
        assert(!barge_in_gate_process(true, kNearEnergy, kNoiseFloor));
    }
    for (size_t i = 7U; i < 20U; ++i) {
        assert(!barge_in_gate_process(false, kNearEnergy, kNoiseFloor));
    }
}

static void test_sparse_vad_speech_does_not_trigger(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 20U; ++i) {
        bool speech = (i % 3U) == 0U;
        assert(!barge_in_gate_process(speech, kNearEnergy, kNoiseFloor));
    }
}

static void test_insufficient_near_energy_does_not_trigger(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 20U; ++i) {
        assert(!barge_in_gate_process(true, kNoiseFloor, kNoiseFloor));
    }
}

static void test_small_energy_margin_above_noise_floor_does_not_trigger(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 20U; ++i) {
        assert(!barge_in_gate_process(true, 149U, 100U));
    }
}

static void test_fifty_percent_energy_margin_still_triggers(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 4U; ++i) {
        assert(!barge_in_gate_process(false, 150U, 100U));
    }
    for (size_t i = 0; i < 16U; ++i) {
        assert(barge_in_gate_process(true, 150U, 100U) == (i == 15U));
    }
}

static void test_zero_noise_floor_fails_closed(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 20U; ++i) {
        assert(!barge_in_gate_process(true, UINT64_MAX, 0U));
    }
}

static void test_high_energy_without_vad_does_not_trigger(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 20U; ++i) {
        assert(!barge_in_gate_process(false, UINT64_MAX, 0U));
    }
}

static void test_reset_drops_partial_history(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 12U; ++i) {
        assert(!barge_in_gate_process(true, kNearEnergy, kNoiseFloor));
    }

    barge_in_gate_reset();
    for (size_t i = 0; i < 8U; ++i) {
        assert(!barge_in_gate_process(true, kNearEnergy, kNoiseFloor));
    }
}

static void test_energy_comparison_is_saturating_at_uint64_limit(void)
{
    barge_in_gate_reset();

    for (size_t i = 0; i < 4U; ++i) {
        assert(!barge_in_gate_process(false, UINT64_MAX, UINT64_MAX - 1U));
    }
    for (size_t i = 0; i < 20U; ++i) {
        assert(!barge_in_gate_process(true, UINT64_MAX, UINT64_MAX - 1U));
    }
}

int main(void)
{
    test_exactly_sixteen_speech_frames_in_twenty_triggers();
    test_single_frame_spike_does_not_trigger();
    test_seven_frame_short_sound_does_not_trigger();
    test_sparse_vad_speech_does_not_trigger();
    test_insufficient_near_energy_does_not_trigger();
    test_small_energy_margin_above_noise_floor_does_not_trigger();
    test_fifty_percent_energy_margin_still_triggers();
    test_zero_noise_floor_fails_closed();
    test_high_energy_without_vad_does_not_trigger();
    test_reset_drops_partial_history();
    test_energy_comparison_is_saturating_at_uint64_limit();
    puts("barge_in_gate_host_test: PASS");
    return 0;
}
