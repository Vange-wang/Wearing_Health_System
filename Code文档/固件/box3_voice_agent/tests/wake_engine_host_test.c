#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "wake_engine.h"

static bool s_detect_next;

static bool fake_detect(const int16_t *samples, size_t sample_count, void *context)
{
    (void)samples;
    (void)sample_count;
    (void)context;
    bool detected = s_detect_next;
    s_detect_next = false;
    return detected;
}

static void fill_frame(int16_t *frame, int16_t value)
{
    for (size_t i = 0; i < WAKE_ENGINE_FRAME_SAMPLES; ++i) {
        frame[i] = value;
    }
}

static void begin_tail_candidate(int16_t *frame)
{
    s_detect_next = true;
    fill_frame(frame, 1000);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_DROP);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM);
    uint32_t events = wake_engine_take_events();
    assert((events & WAKE_ENGINE_EVENT_MODEL_HIT) != 0U);
    assert((events & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);
}

static void confirm_tail_candidate(int16_t *frame)
{
    fill_frame(frame, 0);
    for (int i = 0; i < 8; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_ACK_PLAYING);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) != 0U);
}

static void test_tail_confirmation_requires_eight_low_frames(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    s_detect_next = true;
    fill_frame(frame, 1000);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_DROP);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM);
    uint32_t events = wake_engine_take_events();
    assert((events & WAKE_ENGINE_EVENT_MODEL_HIT) != 0U);
    assert((events & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);

    fill_frame(frame, 0);
    for (int i = 0; i < 7; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
        assert(wake_engine_state() == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM);
        assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);
    }
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_DROP);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_ACK_PLAYING);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) != 0U);
    wake_engine_deinit();
}

static void test_tail_confirmation_high_frame_resets_low_run(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    fill_frame(frame, 0);
    for (int i = 0; i < 7; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    fill_frame(frame, 1000);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_DROP);
    fill_frame(frame, 0);
    for (int i = 0; i < 7; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_DROP);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_ACK_PLAYING);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) != 0U);
    wake_engine_deinit();
}

static void test_tail_candidate_rejects_after_thirty_frames(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    uint32_t stopped_generation = 0;
    bool cancel_round = false;

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    assert(wake_engine_capture_begin_pending());
    assert(wake_engine_bind_capture(3U));
    fill_frame(frame, 1000);
    for (int i = 0; i < 30; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_IDLE);
    uint32_t events = wake_engine_take_events();
    assert((events & WAKE_ENGINE_EVENT_CANDIDATE_REJECTED) != 0U);
    assert((events & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == 3U);
    assert(cancel_round);
    assert(wake_engine_should_cancel(3U));
    wake_engine_deinit();
}

static void test_key_takes_over_during_tail_confirmation(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    assert(wake_engine_bind_capture(4U));
    wake_engine_begin_key(5U);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_KEY);
    assert((wake_engine_take_events() &
            WAKE_ENGINE_EVENT_CANCELLED_BY_KEY) != 0U);
    assert(wake_engine_should_cancel(4U));
    wake_engine_deinit();
}

static void test_ack_blocks_vad_until_explicit_completion(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_capture_begin_pending());
    assert(wake_engine_bind_capture(5U));
    uint32_t ack_generation = 0;
    assert(wake_engine_take_ack_request(&ack_generation));
    assert(ack_generation == 5U);
    assert(!wake_engine_take_ack_request(&ack_generation));

    /* Speaker leakage during the local acknowledgement must never reach VAD. */
    for (int i = 0; i < 50; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_ACK_PLAYING);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_START) == 0U);

    assert(wake_engine_ack_complete(5U));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_ACK_COMPLETE) != 0U);
    wake_engine_deinit();
}

static void test_key_takes_over_during_ack(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_bind_capture(6U));

    wake_engine_begin_key(7U);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_KEY);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_CANCELLED_BY_KEY) != 0U);
    assert(!wake_engine_ack_complete(6U));
    wake_engine_deinit();
}

static void test_ack_speech_is_buffered_but_waits_for_ack_completion(void)
{
    const uint32_t generation = 6U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t pre_roll[WAKE_ENGINE_PRE_ROLL_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_bind_capture(generation));

    fill_frame(frame, 900);
    for (int i = 0; i < 16; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    assert(!wake_engine_note_ack_speech(generation + 1U));
    assert(wake_engine_note_ack_speech(generation));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_ACK_PLAYING);

    assert(wake_engine_ack_complete(generation));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    const uint32_t events = wake_engine_take_events();
    assert((events & WAKE_ENGINE_EVENT_ACK_COMPLETE) != 0U);
    assert((events & WAKE_ENGINE_EVENT_SPEECH_START) != 0U);
    const size_t count = wake_engine_read_pre_roll(
        pre_roll, WAKE_ENGINE_PRE_ROLL_SAMPLES, generation);
    assert(count == 16U * WAKE_ENGINE_FRAME_SAMPLES);
    assert(pre_roll[0] == 900);
    assert(pre_roll[count - 1U] == 900);
    wake_engine_deinit();
}

static void test_wake_then_speech_emits_only_post_wake_preroll(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t pre_roll[WAKE_ENGINE_PRE_ROLL_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_capture_begin_pending());
    assert(wake_engine_bind_capture(7U));
    assert(wake_engine_ack_complete(7U));
    (void)wake_engine_take_events();

    /* 100 ms post-wake silence + 100 ms speech: F is the confirmation point,
     * so F-200 ms clamps exactly to the first post-wake frame. */
    for (int i = 0; i < 10; ++i) {
        fill_frame(frame, (int16_t)(100 + i));
        wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    for (int i = 0; i < 10; ++i) {
        fill_frame(frame, (int16_t)(600 + i));
        wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }

    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_START) != 0U);
    size_t count = wake_engine_read_pre_roll(
        pre_roll, WAKE_ENGINE_PRE_ROLL_SAMPLES, 7U);
    assert(count == 20U * WAKE_ENGINE_FRAME_SAMPLES);
    assert(pre_roll[0] == 100);
    assert(pre_roll[count - 1U] == 609);
    assert(wake_engine_read_pre_roll(pre_roll, 1U, 7U) == 0U);
    wake_engine_deinit();
}

static void test_sixty_seconds_without_speech_ends_session(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t output[WAKE_ENGINE_PRE_ROLL_SAMPLES];
    uint32_t stopped_generation = 0;
    bool cancel_round = true;

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_bind_capture(11U));
    assert(wake_engine_ack_complete(11U));
    (void)wake_engine_take_events();

    fill_frame(frame, 0);
    for (int i = 0; i < 300; ++i) {
        wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);

    for (int i = 300; i < 5999; ++i) {
        wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);

    wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);

    assert(wake_engine_state() == WAKE_ENGINE_STATE_IDLE);
    const uint32_t timeout_events = wake_engine_take_events();
    assert((timeout_events & WAKE_ENGINE_EVENT_NO_SPEECH_TIMEOUT) != 0U);
    assert((timeout_events & WAKE_ENGINE_EVENT_SESSION_TIMEOUT) != 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == 11U);
    assert(!cancel_round);
    assert(wake_engine_read_pre_roll(output, WAKE_ENGINE_PRE_ROLL_SAMPLES,
                                     11U) == 0U);
    wake_engine_deinit();
}

static void assert_preroll_after_silence(int silence_frames,
                                         uint32_t generation)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t pre_roll[WAKE_ENGINE_PRE_ROLL_SAMPLES];
    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_bind_capture(generation));
    assert(wake_engine_ack_complete(generation));
    (void)wake_engine_take_events();
    for (int i = 0; i < silence_frames; ++i) {
        fill_frame(frame, (int16_t)(100 + i));
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    for (int i = 0; i < 10; ++i) {
        fill_frame(frame, (int16_t)(700 + i));
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    size_t count = wake_engine_read_pre_roll(
        pre_roll, WAKE_ENGINE_PRE_ROLL_SAMPLES, generation);
    assert(count == 3200U);
    assert(pre_roll[0] == (int16_t)(100 + silence_frames - 10));
    assert(pre_roll[count - 1U] == 709);
    wake_engine_deinit();
}

static void test_preroll_cursor_for_point_one_point_five_and_two_point_nine_seconds(void)
{
    assert_preroll_after_silence(10, 12U);
    assert_preroll_after_silence(50, 13U);
    assert_preroll_after_silence(290, 14U);
}

static void start_bound_wake_upload(uint32_t generation)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t discarded[WAKE_ENGINE_PRE_ROLL_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_bind_capture(generation));
    assert(wake_engine_ack_complete(generation));
    (void)wake_engine_take_events();
    for (int i = 0; i < 20; ++i) {
        fill_frame(frame, i < 10 ? 0 : 700);
        wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_START) != 0U);
    assert(wake_engine_read_pre_roll(discarded,
                                     WAKE_ENGINE_PRE_ROLL_SAMPLES,
                                     generation) == 3200U);
}

static void test_hold_is_replayed_in_order_when_speech_recovers(void)
{
    const uint32_t generation = 17U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t hold[WAKE_ENGINE_HOLD_SAMPLES];
    start_bound_wake_upload(generation);

    fill_frame(frame, 700);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_MAIN);

    fill_frame(frame, 0);
    for (int i = 0; i < 8; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_MAIN);
    }
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_END_PENDING) != 0U);

    for (int i = 0; i < 5; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_HOLD);
    }
    fill_frame(frame, 700);
    for (int i = 0; i < 6; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_HOLD);
    }
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_CONTINUE) != 0U);

    size_t count = wake_engine_read_hold(hold, WAKE_ENGINE_HOLD_SAMPLES,
                                         generation);
    assert(count == 11U * WAKE_ENGINE_FRAME_SAMPLES);
    assert(hold[0] == 0);
    assert(hold[5U * WAKE_ENGINE_FRAME_SAMPLES] == 700);
    assert(hold[count - 1U] == 700);
    assert(wake_engine_read_hold(hold, 1U, generation) == 0U);

    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_MAIN);
    wake_engine_deinit();
}

static void test_end_window_finishes_when_backlog_is_empty(void)
{
    const uint32_t generation = 21U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t hold[WAKE_ENGINE_HOLD_SAMPLES];
    uint32_t stopped_generation = 0;
    bool cancel_round = true;
    start_bound_wake_upload(generation);

    fill_frame(frame, 0);
    for (int i = 0; i < 8; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_MAIN);
    }
    (void)wake_engine_take_events();
    wake_engine_set_backlog(generation, 0U, 0U, 0U);
    for (int i = 0; i < 30; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_HOLD);
    }

    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_END) != 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == generation);
    assert(!cancel_round);
    assert(!wake_engine_should_cancel(generation));
    assert(wake_engine_read_hold(hold, WAKE_ENGINE_HOLD_SAMPLES,
                                 generation) == 0U);
    wake_engine_deinit();
}

static void test_nonzero_backlog_requests_clean_drain_stop(void)
{
    const uint32_t generation = 23U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    uint32_t stopped_generation = 0;
    bool cancel_round = false;
    start_bound_wake_upload(generation);

    fill_frame(frame, 0);
    for (int i = 0; i < 8; ++i) {
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    (void)wake_engine_take_events();
    wake_engine_set_backlog(generation, 0U, 64U, 0U);

    /* 24 low frames + 6 high frames fill W exactly; window-full must win over
     * the recovery threshold reached by that same final frame. */
    for (int i = 0; i < 24; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_HOLD);
    }
    fill_frame(frame, 700);
    for (int i = 0; i < 6; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_HOLD);
    }

    uint32_t events = wake_engine_take_events();
    assert((events & WAKE_ENGINE_EVENT_SPEECH_END) != 0U);
    assert((events & WAKE_ENGINE_EVENT_SPEECH_CONTINUE) == 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == generation);
    assert(!cancel_round);
    assert(!wake_engine_should_cancel(generation));
    wake_engine_deinit();
}

static void test_key_override_isolates_generations(void)
{
    const uint32_t wake_generation = 31U;
    const uint32_t key_generation = 32U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    start_bound_wake_upload(wake_generation);

    wake_engine_begin_key(key_generation);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_KEY);
    assert((wake_engine_take_events() &
            WAKE_ENGINE_EVENT_CANCELLED_BY_KEY) != 0U);
    assert(wake_engine_should_cancel(wake_generation));
    assert(!wake_engine_should_cancel(key_generation));

    s_detect_next = true;
    fill_frame(frame, 1000);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_MAIN);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);

    wake_engine_cancel_key_capture(key_generation);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_IDLE);
    wake_engine_deinit();
}

static void test_key_override_drops_stale_wake_events(void)
{
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    wake_engine_begin_key(35U);
    uint32_t events = wake_engine_take_events();
    assert(events == WAKE_ENGINE_EVENT_CANCELLED_BY_KEY);
    wake_engine_deinit();
}

static void test_playing_suppresses_detection_and_finish_resets_round(void)
{
    const uint32_t generation = 41U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    start_bound_wake_upload(generation);

    assert(wake_engine_mark_playing(generation));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_PLAYING);

    s_detect_next = true;
    fill_frame(frame, 1000);
    assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
           WAKE_ENGINE_ROUTE_DROP);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_TRIGGERED) == 0U);

    assert(!wake_engine_finish_round(generation + 1U, false));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_PLAYING);
    assert(wake_engine_finish_round(generation, false));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_IDLE);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_NONE);
    assert(wake_engine_should_cancel(generation));
    wake_engine_deinit();
}

static void test_response_finish_rearms_without_ack_and_uses_new_generation(void)
{
    const uint32_t old_generation = 42U;
    const uint32_t new_generation = 43U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t pre_roll[WAKE_ENGINE_PRE_ROLL_SAMPLES];
    uint32_t ack_generation = 0U;

    start_bound_wake_upload(old_generation);
    assert(wake_engine_mark_playing(old_generation));
    assert(wake_engine_finish_round(old_generation, true));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_WAKE);
    assert(wake_engine_generation() == 0U);
    assert(wake_engine_should_cancel(old_generation));
    assert((wake_engine_take_events() &
            WAKE_ENGINE_EVENT_SESSION_REARMED) != 0U);

    fill_frame(frame, 800);
    for (int i = 0; i < 10; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_capture_begin_pending());
    assert(!wake_engine_take_ack_request(&ack_generation));
    assert(wake_engine_bind_capture(new_generation));
    assert(wake_engine_generation() == new_generation);
    assert(wake_engine_read_pre_roll(pre_roll,
                                     WAKE_ENGINE_PRE_ROLL_SAMPLES,
                                     new_generation) ==
           10U * WAKE_ENGINE_FRAME_SAMPLES);
    wake_engine_deinit();
}

static void test_service_failure_rearms_full_session_window(void)
{
    const uint32_t generation = 44U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    start_bound_wake_upload(generation);
    assert(wake_engine_finish_round(generation, true));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);
    assert((wake_engine_take_events() &
            WAKE_ENGINE_EVENT_SESSION_REARMED) != 0U);

    fill_frame(frame, 0);
    for (int i = 0; i < 5999; ++i) {
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);
    wake_engine_deinit();
}

static void test_speech_at_fifty_five_seconds_starts_round(void)
{
    const uint32_t generation = 45U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];

    assert(wake_engine_init_for_test(fake_detect, NULL));
    begin_tail_candidate(frame);
    confirm_tail_candidate(frame);
    assert(wake_engine_bind_capture(generation));
    assert(wake_engine_ack_complete(generation));
    (void)wake_engine_take_events();

    fill_frame(frame, 0);
    for (int i = 0; i < 5500; ++i) {
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_WAIT_SPEECH);

    fill_frame(frame, 800);
    for (int i = 0; i < 10; ++i) {
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_generation() == generation);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_START) != 0U);
    wake_engine_deinit();
}

static void test_key_takeover_clears_rearmed_session(void)
{
    const uint32_t wake_generation = 46U;
    const uint32_t key_generation = 47U;

    start_bound_wake_upload(wake_generation);
    assert(wake_engine_finish_round(wake_generation, true));
    (void)wake_engine_take_events();

    wake_engine_begin_key(key_generation);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_KEY);
    assert((wake_engine_take_events() &
            WAKE_ENGINE_EVENT_CANCELLED_BY_KEY) != 0U);
    wake_engine_cancel_key_capture(key_generation);
    assert(wake_engine_state() == WAKE_ENGINE_STATE_IDLE);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_NONE);
    wake_engine_deinit();
}

static void test_barge_in_preserves_preroll_for_new_generation(void)
{
    const uint32_t playing_generation = 48U;
    const uint32_t capture_generation = 49U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    int16_t pre_roll[WAKE_ENGINE_PRE_ROLL_SAMPLES];
    uint32_t ack_generation = 0U;

    start_bound_wake_upload(playing_generation);
    assert(wake_engine_mark_playing(playing_generation));
    fill_frame(frame, 900);
    for (int i = 0; i < 16; ++i) {
        assert(wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES) ==
               WAKE_ENGINE_ROUTE_DROP);
    }

    assert(!wake_engine_note_barge_in(playing_generation + 1U));
    assert(wake_engine_note_barge_in(playing_generation));
    assert(wake_engine_state() == WAKE_ENGINE_STATE_UPLOADING);
    assert(wake_engine_trigger_mode() == WAKE_ENGINE_MODE_WAKE);
    assert(wake_engine_generation() == 0U);
    assert(wake_engine_should_cancel(playing_generation));
    assert(wake_engine_capture_begin_pending());
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_BARGE_IN) != 0U);
    assert(!wake_engine_take_ack_request(&ack_generation));

    assert(wake_engine_bind_capture(capture_generation));
    const size_t count = wake_engine_read_pre_roll(
        pre_roll, WAKE_ENGINE_PRE_ROLL_SAMPLES, capture_generation);
    assert(count == 16U * WAKE_ENGINE_FRAME_SAMPLES);
    assert(pre_roll[0] == 900);
    assert(pre_roll[count - 1U] == 900);
    wake_engine_deinit();
}

static void test_fifteen_second_capture_limit_requests_clean_stop(void)
{
    const uint32_t generation = 43U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    uint32_t stopped_generation = 0;
    bool cancel_round = true;

    assert(wake_engine_init_for_test(fake_detect, NULL));
    wake_engine_begin_key(generation);
    fill_frame(frame, 700);
    for (int i = 0; i < 1500; ++i) {
        wake_engine_note_capture_samples(generation,
                                         WAKE_ENGINE_FRAME_SAMPLES);
    }

    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_ROUND_TIMEOUT) != 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == generation);
    assert(!cancel_round);
    assert(!wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    wake_engine_deinit();
}

static void test_capture_overflow_cancels_current_generation(void)
{
    const uint32_t generation = 47U;
    uint32_t stopped_generation = 0;
    bool cancel_round = false;

    assert(wake_engine_init_for_test(fake_detect, NULL));
    wake_engine_begin_key(generation);
    wake_engine_report_capture_overflow(generation);
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_BUFFER_OVERFLOW) != 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == generation);
    assert(cancel_round);
    assert(wake_engine_should_cancel(generation));
    wake_engine_deinit();
}

static void test_backlog_field_updates_do_not_cancel_clean_stop(void)
{
    const uint32_t generation = 49U;
    int16_t frame[WAKE_ENGINE_FRAME_SAMPLES];
    uint32_t stopped_generation = 0;
    bool cancel_round = false;
    start_bound_wake_upload(generation);

    wake_engine_set_backlog(generation, 100U, 64U, 2U);
    wake_engine_set_ring_pending(generation, 0U);
    wake_engine_set_transport_backlog(generation, 64U, 0U);

    fill_frame(frame, 0);
    for (int i = 0; i < 8 + 30; ++i) {
        (void)wake_engine_process_frame(frame, WAKE_ENGINE_FRAME_SAMPLES);
    }
    assert((wake_engine_take_events() & WAKE_ENGINE_EVENT_SPEECH_END) != 0U);
    assert(wake_engine_take_stop_request(&stopped_generation, &cancel_round));
    assert(stopped_generation == generation);
    assert(!cancel_round);
    assert(!wake_engine_should_cancel(generation));
    wake_engine_deinit();
}

int main(void)
{
    test_tail_confirmation_requires_eight_low_frames();
    test_tail_confirmation_high_frame_resets_low_run();
    test_tail_candidate_rejects_after_thirty_frames();
    test_key_takes_over_during_tail_confirmation();
    test_ack_blocks_vad_until_explicit_completion();
    test_key_takes_over_during_ack();
    test_ack_speech_is_buffered_but_waits_for_ack_completion();
    test_wake_then_speech_emits_only_post_wake_preroll();
    test_sixty_seconds_without_speech_ends_session();
    test_preroll_cursor_for_point_one_point_five_and_two_point_nine_seconds();
    test_hold_is_replayed_in_order_when_speech_recovers();
    test_end_window_finishes_when_backlog_is_empty();
    test_nonzero_backlog_requests_clean_drain_stop();
    test_key_override_isolates_generations();
    test_key_override_drops_stale_wake_events();
    test_playing_suppresses_detection_and_finish_resets_round();
    test_response_finish_rearms_without_ack_and_uses_new_generation();
    test_service_failure_rearms_full_session_window();
    test_speech_at_fifty_five_seconds_starts_round();
    test_key_takeover_clears_rearmed_session();
    test_barge_in_preserves_preroll_for_new_generation();
    test_fifteen_second_capture_limit_requests_clean_stop();
    test_capture_overflow_cancels_current_generation();
    test_backlog_field_updates_do_not_cancel_clean_stop();
    puts("wake_engine_host_test: PASS");
    return 0;
}
