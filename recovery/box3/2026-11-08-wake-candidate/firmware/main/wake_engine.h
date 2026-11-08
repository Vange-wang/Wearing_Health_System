#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WAKE_ENGINE_FRAME_SAMPLES 160U
#define WAKE_ENGINE_PRE_ROLL_SAMPLES 4800U
#define WAKE_ENGINE_HOLD_SAMPLES 8192U

typedef enum {
    WAKE_ENGINE_STATE_IDLE = 0,
    WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM,
    WAKE_ENGINE_STATE_ACK_PLAYING,
    WAKE_ENGINE_STATE_WAIT_SPEECH,
    WAKE_ENGINE_STATE_UPLOADING,
    WAKE_ENGINE_STATE_PLAYING,
} wake_engine_state_t;

typedef enum {
    WAKE_ENGINE_MODE_NONE = 0,
    WAKE_ENGINE_MODE_WAKE,
    WAKE_ENGINE_MODE_KEY,
} wake_engine_trigger_mode_t;

typedef enum {
    WAKE_ENGINE_ROUTE_DROP = 0,
    WAKE_ENGINE_ROUTE_MAIN,
    WAKE_ENGINE_ROUTE_HOLD,
} wake_engine_frame_route_t;

typedef struct {
    int64_t last_progress_us;
} wake_response_progress_t;

typedef enum {
    WAKE_RESPONSE_DATA = 0,
    WAKE_RESPONSE_AGAIN,
    WAKE_RESPONSE_COMPLETE_EOF,
    WAKE_RESPONSE_TIMEOUT,
    WAKE_RESPONSE_TRUNCATED_EOF,
    WAKE_RESPONSE_HARD_ERROR,
} wake_response_result_t;

enum {
    WAKE_ENGINE_EVENT_TRIGGERED = 1U << 0,
    WAKE_ENGINE_EVENT_SPEECH_START = 1U << 1,
    WAKE_ENGINE_EVENT_NO_SPEECH_TIMEOUT = 1U << 2,
    WAKE_ENGINE_EVENT_SPEECH_END_PENDING = 1U << 3,
    WAKE_ENGINE_EVENT_SPEECH_CONTINUE = 1U << 4,
    WAKE_ENGINE_EVENT_SPEECH_END = 1U << 5,
    WAKE_ENGINE_EVENT_BACKLOG_STALL = 1U << 6,
    WAKE_ENGINE_EVENT_CANCELLED_BY_KEY = 1U << 7,
    WAKE_ENGINE_EVENT_ROUND_TIMEOUT = 1U << 8,
    WAKE_ENGINE_EVENT_BUFFER_OVERFLOW = 1U << 9,
    WAKE_ENGINE_EVENT_ACK_COMPLETE = 1U << 10,
    WAKE_ENGINE_EVENT_MODEL_HIT = 1U << 11,
    WAKE_ENGINE_EVENT_CANDIDATE_REJECTED = 1U << 12,
    WAKE_ENGINE_EVENT_SESSION_REARMED = 1U << 13,
    WAKE_ENGINE_EVENT_SESSION_TIMEOUT = 1U << 14,
    WAKE_ENGINE_EVENT_BARGE_IN = 1U << 15,
    WAKE_ENGINE_EVENT_UNBOUND_CANCELLED = 1U << 16,
};

bool wake_engine_init(void);
void wake_engine_deinit(void);
bool wake_engine_available(void);

#ifdef WAKE_ENGINE_HOST_TEST
typedef bool (*wake_engine_test_detector_t)(const int16_t *samples,
                                             size_t sample_count,
                                             void *context);
bool wake_engine_init_for_test(wake_engine_test_detector_t detector,
                               void *context);
#endif

wake_engine_frame_route_t wake_engine_process_frame(const int16_t *samples,
                                                     size_t sample_count);
wake_engine_state_t wake_engine_state(void);
wake_engine_trigger_mode_t wake_engine_trigger_mode(void);
uint32_t wake_engine_generation(void);
uint64_t wake_engine_sample_index(void);
uint32_t wake_engine_take_events(void);
bool wake_engine_capture_begin_pending(void);
bool wake_engine_bind_capture(uint32_t generation);
bool wake_engine_take_ack_request(uint32_t *generation);
/* note/complete are PCM-producer operations; playback_done only publishes. */
bool wake_engine_ack_protected(uint32_t generation);
void wake_engine_ack_playback_done(uint32_t generation);
bool wake_engine_ack_completion_pending(uint32_t generation);
bool wake_engine_note_ack_speech(uint32_t generation);
bool wake_engine_ack_complete(uint32_t generation);
void wake_engine_begin_key(uint32_t generation);
void wake_engine_cancel_key_capture(uint32_t generation);
bool wake_engine_mark_playing(uint32_t generation);
void wake_engine_enable_segmented_input(void);
bool wake_engine_wait_candidate(uint32_t generation);
bool wake_engine_finish_round(uint32_t generation, bool keep_session);
bool wake_engine_note_barge_in(uint32_t generation);
bool wake_engine_defer_input(uint32_t generation);
bool wake_engine_restart_deferred_input(uint32_t generation);
/* 0 stale, 1 playback, 2 confirmed speech retained for next turn. */
int wake_engine_commit_output(uint32_t generation,bool success);
/* Caller holds its capture-state lock. admit must be synchronous/nonblocking;
 * it runs under the wake-state lock so speech confirmation cannot cross it. */
bool wake_engine_admit_output(uint32_t generation,bool (*admit)(void *),void *context);
void wake_engine_note_capture_samples(uint32_t generation,
                                      size_t sample_count);
void wake_engine_report_capture_overflow(uint32_t generation);
bool wake_engine_take_stop_request(uint32_t *generation, bool *cancel_round);
void wake_engine_set_backlog(uint32_t generation, size_t ring_pending,
                             size_t in_flight_bytes, size_t framing_pending);
void wake_engine_set_ring_pending(uint32_t generation, size_t ring_pending);
void wake_engine_set_transport_backlog(uint32_t generation,
                                       size_t in_flight_bytes,
                                       size_t framing_pending);
bool wake_engine_should_cancel(uint32_t generation);
size_t wake_engine_read_pre_roll(int16_t *samples, size_t max_samples,
                                 uint32_t generation);
size_t wake_engine_read_hold(int16_t *samples, size_t max_samples,
                             uint32_t generation);
void wake_response_progress_init(wake_response_progress_t *progress,
                                 int64_t now_us);
wake_response_result_t wake_response_classify(
    wake_response_progress_t *progress, int read_result, int eagain_result,
    bool protocol_complete, int64_t now_us);


/* Exact unbound request identity; cancellation is complete only at producer commit. */
bool wake_engine_unbound_request(uint64_t *ticket);
bool wake_engine_cancel_unbound(uint64_t ticket);
#ifdef __cplusplus
}
#endif


#ifdef VOICE_WAKE_DIAGNOSTICS
typedef struct {
    uint32_t valid,available,state,mode,generation,pending,ack_pending,cancelled;
    uint32_t frames,detect_calls,model_hits,sample_low;
} wake_engine_diag_t;
bool wake_engine_diag_snapshot(wake_engine_diag_t *out);
#endif
