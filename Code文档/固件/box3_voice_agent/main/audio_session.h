#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Exactly one playback/network lease may exist at a time. */
typedef enum {
    AUDIO_SESSION_OWNER_NONE = 0,
    AUDIO_SESSION_OWNER_TALK,
    AUDIO_SESSION_OWNER_ALERT,
} audio_session_owner_t;

/* Initializes the statically allocated state, lock, and PCM rings. */
void audio_session_init(void);

/* Button-down path: starts a new capture generation and revokes an alert lease. */
bool audio_session_begin_capture(void);

/* Promotes the current press after the long-press threshold. */
bool audio_session_confirm_long_press(void);

/* Button-up path. Returns true only when an unconfirmed short press was discarded. */
bool audio_session_cancel_short_press(void);

bool audio_session_capture_pending(void);
bool audio_session_capture_confirmed(void);
bool audio_session_capture_active(void);
int64_t audio_session_capture_elapsed_us(void);
uint32_t audio_session_capture_generation(void);

/* Capture producer/HTTP consumer interface. Samples are mono 16-bit PCM. */
size_t audio_session_write_capture(const int16_t *samples, size_t sample_count);
size_t audio_session_read_capture(int16_t *samples, size_t max_samples);
bool audio_session_capture_has_buffered(void);
void audio_session_complete_capture(uint32_t generation);

/* Exclusive lease/cancellation interface shared by talk and alert paths. */
bool audio_session_acquire_playback(audio_session_owner_t owner);
void audio_session_cancel_alert(void);
bool audio_session_should_cancel(audio_session_owner_t owner);
bool audio_session_owner_is(audio_session_owner_t owner);
void audio_session_release(audio_session_owner_t owner);

#ifdef __cplusplus
}
#endif
