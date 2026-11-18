#include "duplex_audio.h"

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    bool aec_success;
    bool vad_speech;
    bool remove_echo;
    size_t vad_speech_frames;
    size_t aec_calls;
    size_t vad_calls;
    int16_t first_reference_sample;
} fake_audio_t;

enum {
    TEST_BARGE_AEC_FRAMES =
        (16U * DUPLEX_AUDIO_VAD_FRAME_SAMPLES) /
        DUPLEX_AUDIO_AEC_FRAME_SAMPLES,
};

static bool fake_aec_process(void *context, const int16_t *microphone,
                             const int16_t *reference, int16_t *output,
                             size_t sample_count)
{
    fake_audio_t *fake = (fake_audio_t *)context;
    if (fake->aec_calls == 0U) {
        fake->first_reference_sample = reference[0];
    }
    fake->aec_calls++;
    if (fake->remove_echo) {
        memset(output, 0, sample_count * sizeof(*output));
    } else {
        memcpy(output, microphone, sample_count * sizeof(*output));
    }
    return fake->aec_success;
}

static void process_barge_window(const int16_t *capture, int16_t *output)
{
    for (size_t i = 0U; i < TEST_BARGE_AEC_FRAMES; ++i) {
        assert(duplex_audio_process_capture_stereo(
                   capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, output,
                   DUPLEX_AUDIO_AEC_FRAME_SAMPLES) ==
               DUPLEX_AUDIO_AEC_FRAME_SAMPLES);
    }
}

static bool fake_vad_process(void *context, const int16_t *samples,
                             size_t sample_count)
{
    fake_audio_t *fake = (fake_audio_t *)context;
    (void)samples;
    assert(sample_count == DUPLEX_AUDIO_VAD_FRAME_SAMPLES);
    fake->vad_calls++;
    return fake->vad_speech &&
           (fake->vad_speech_frames == 0U ||
            fake->vad_calls <= fake->vad_speech_frames);
}

static void init_fake(fake_audio_t *fake)
{
    duplex_audio_test_ops_t ops = {
        .aec_process = fake_aec_process,
        .vad_process = fake_vad_process,
    };
    memset(fake, 0, sizeof(*fake));
    fake->aec_success = true;
    assert(duplex_audio_init_for_test(&ops, fake));

    /* 真机采集任务在播放前持续建立环境噪声底；host test 同样先走一次
     * 无播放公开路径，避免用“未校准的零噪声底”制造假阳性。 */
    int16_t ambient[2U * DUPLEX_AUDIO_VAD_FRAME_SAMPLES];
    int16_t ambient_output[DUPLEX_AUDIO_VAD_FRAME_SAMPLES];
    for (size_t i = 0U; i < DUPLEX_AUDIO_VAD_FRAME_SAMPLES; ++i) {
        ambient[i * 2U] = 100;
        ambient[i * 2U + 1U] = 100;
    }
    assert(duplex_audio_process_capture_stereo(
               ambient, DUPLEX_AUDIO_VAD_FRAME_SAMPLES, ambient_output,
               DUPLEX_AUDIO_VAD_FRAME_SAMPLES) ==
           DUPLEX_AUDIO_VAD_FRAME_SAMPLES);
}

static void fill_stereo(int16_t *samples, size_t frames, int16_t left,
                        int16_t right)
{
    for (size_t i = 0; i < frames; ++i) {
        samples[i * 2U] = left;
        samples[i * 2U + 1U] = right;
    }
}

static void test_no_playback_bypasses_aec_and_vad(void)
{
    fake_audio_t fake;
    int16_t input[2U * DUPLEX_AUDIO_VAD_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_VAD_FRAME_SAMPLES];

    init_fake(&fake);
    fill_stereo(input, DUPLEX_AUDIO_VAD_FRAME_SAMPLES, 200, 600);
    assert(duplex_audio_process_capture_stereo(
               input, DUPLEX_AUDIO_VAD_FRAME_SAMPLES, output,
               DUPLEX_AUDIO_VAD_FRAME_SAMPLES) == DUPLEX_AUDIO_VAD_FRAME_SAMPLES);
    for (size_t i = 0; i < DUPLEX_AUDIO_VAD_FRAME_SAMPLES; ++i) {
        assert(output[i] == 400);
    }
    assert(fake.aec_calls == 0U);
    assert(fake.vad_calls == 0U);
}

static void test_ack_keeps_speech_but_never_emits_barge_in(void)
{
    fake_audio_t fake;
    int16_t playback[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    assert(duplex_audio_begin_playback(DUPLEX_PLAYBACK_ACK_PROTECTED, 7U));
    fill_stereo(playback, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 200, 600);
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    assert(duplex_audio_push_playback_stereo(
               playback, DUPLEX_AUDIO_AEC_FRAME_SAMPLES) == DUPLEX_AUDIO_AEC_FRAME_SAMPLES);
    process_barge_window(capture, output);
    assert(fake.aec_calls == TEST_BARGE_AEC_FRAMES);
    assert(fake.vad_calls == 16U);
    assert(fake.first_reference_sample == 400);
    duplex_audio_end_playback();
    assert(duplex_audio_take_near_speech(&generation));
    assert(generation == 7U);
    assert(!duplex_audio_take_near_speech(&generation));
    assert(!duplex_audio_take_barge_in(&generation));
}

static void test_response_speech_emits_barge_in_for_current_generation(void)
{
    fake_audio_t fake;
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 11U));
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    process_barge_window(capture, output);
    assert(duplex_audio_take_barge_in(&generation));
    assert(generation == 11U);
    assert(!duplex_audio_take_barge_in(&generation));
}

static void test_near_speech_notification_is_one_shot_per_playback(void)
{
    fake_audio_t fake;
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    assert(duplex_audio_begin_playback(DUPLEX_PLAYBACK_ACK_PROTECTED, 12U));
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    process_barge_window(capture, output);
    assert(duplex_audio_take_near_speech(&generation));
    assert(generation == 12U);

    process_barge_window(capture, output);
    assert(!duplex_audio_take_near_speech(&generation));
    duplex_audio_end_playback();
}

static void test_echo_removed_to_silence_does_not_emit_barge_in(void)
{
    fake_audio_t fake;
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    fake.remove_echo = true;
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 13U));
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    process_barge_window(capture, output);
    assert(!duplex_audio_take_barge_in(&generation));
}

static void test_single_vad_spike_does_not_emit_barge_in(void)
{
    fake_audio_t fake;
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    fake.vad_speech_frames = 1U;
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 15U));
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    process_barge_window(capture, output);
    assert(!duplex_audio_take_barge_in(&generation));
}

static void test_reference_fifo_overflow_fails_closed(void)
{
    fake_audio_t fake;
    int16_t playback[2U * (DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES + 1U)];
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 17U));
    fill_stereo(playback, DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES + 1U, 200, 600);
    assert(duplex_audio_push_playback_stereo(
               playback, DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES + 1U) ==
           DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES);
    assert(duplex_audio_degraded());
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    process_barge_window(capture, output);
    assert(!duplex_audio_take_barge_in(&generation));
}

static void test_new_generation_clears_stale_barge_in(void)
{
    fake_audio_t fake;
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.vad_speech = true;
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 19U));
    process_barge_window(capture, output);
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 23U));
    assert(!duplex_audio_take_barge_in(&generation));
    process_barge_window(capture, output);
    assert(duplex_audio_take_barge_in(&generation));
    assert(generation == 23U);
}

static void test_aec_failure_degrades_and_fails_closed(void)
{
    fake_audio_t fake;
    int16_t capture[2U * DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    uint32_t generation = 0U;

    init_fake(&fake);
    fake.aec_success = false;
    fake.vad_speech = true;
    assert(duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 29U));
    fill_stereo(capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, 1000, 1000);
    assert(duplex_audio_process_capture_stereo(
               capture, DUPLEX_AUDIO_AEC_FRAME_SAMPLES, output,
               DUPLEX_AUDIO_AEC_FRAME_SAMPLES) ==
           DUPLEX_AUDIO_AEC_FRAME_SAMPLES);
    assert(duplex_audio_degraded());
    assert(!duplex_audio_take_barge_in(&generation));
}

static void test_invalid_test_ops_fail_initialization_closed(void)
{
    duplex_audio_test_ops_t invalid_ops = {0};

    assert(!duplex_audio_init_for_test(&invalid_ops, NULL));
    assert(duplex_audio_degraded());
    assert(!duplex_audio_begin_playback(
        DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE, 31U));
}

int main(void)
{
    test_no_playback_bypasses_aec_and_vad();
    test_ack_keeps_speech_but_never_emits_barge_in();
    test_response_speech_emits_barge_in_for_current_generation();
    test_near_speech_notification_is_one_shot_per_playback();
    test_echo_removed_to_silence_does_not_emit_barge_in();
    test_single_vad_spike_does_not_emit_barge_in();
    test_reference_fifo_overflow_fails_closed();
    test_new_generation_clears_stale_barge_in();
    test_aec_failure_degrades_and_fails_closed();
    test_invalid_test_ops_fail_initialization_closed();
    puts("duplex_audio_host_test: PASS");
    return 0;
}
