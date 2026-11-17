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

/* Allocates the bounded capture ring once and initializes state/lock.
 * Returns false when the required PSRAM ring cannot be established. */
bool audio_session_init(void);

/* Button-down path: starts a new capture generation and revokes an alert lease. */
bool audio_session_begin_capture(void);

/* Promotes the current press after the long-press threshold. */
bool audio_session_confirm_long_press(void);

/* Confirms a capture only when the caller still owns the current generation. */
bool audio_session_confirm_capture(uint32_t generation);

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
size_t audio_session_capture_buffered_samples(void);
/* Stops producer writes while preserving buffered PCM for the HTTP consumer. */
bool audio_session_stop_capture(uint32_t generation);
bool audio_session_resume_capture(uint32_t generation);
void audio_session_complete_capture(uint32_t generation);

/* Exclusive lease/cancellation interface shared by talk and alert paths. */
bool audio_session_acquire_playback(audio_session_owner_t owner);
void audio_session_cancel_alert(void);
/* Cancels only the TALK lease bound to the current capture generation. */
bool audio_session_cancel_talk(uint32_t generation);
bool audio_session_should_cancel(audio_session_owner_t owner);
bool audio_session_owner_is(audio_session_owner_t owner);
void audio_session_release(audio_session_owner_t owner);

#ifdef __cplusplus
}
#endif
