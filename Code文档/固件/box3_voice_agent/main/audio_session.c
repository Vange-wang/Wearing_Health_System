#include "audio_session.h"

#include <string.h>

#ifndef AUDIO_SESSION_HOST_TEST
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#endif

/* 384 ms keeps the required first 300 ms plus one 64 ms codec read and margin. */
#define PREBUFFER_SAMPLES 6144U
/* Bounded 512 ms producer/consumer cushion after long-press confirmation. */
#define LIVE_BUFFER_SAMPLES 8192U

typedef enum {
    CAPTURE_IDLE = 0,
    CAPTURE_PENDING,
    CAPTURE_CONFIRMED,
} capture_state_t;

typedef struct {
    capture_state_t capture_state;
    bool capture_active;
    int64_t capture_started_us;
    uint32_t generation;

    audio_session_owner_t owner;
    bool cancel_talk;
    bool cancel_alert;

    size_t pre_read;
    size_t pre_write;
    size_t pre_count;
    size_t live_read;
    size_t live_write;
    size_t live_count;
} audio_session_state_t;

static audio_session_state_t s_state;
static int16_t s_prebuffer[PREBUFFER_SAMPLES];
static int16_t s_live_buffer[LIVE_BUFFER_SAMPLES];

#ifdef AUDIO_SESSION_HOST_TEST
static void state_lock(void) {}
static void state_unlock(void) {}
static int64_t now_us(void) { return 0; }
#else
static StaticSemaphore_t s_lock_storage;
static SemaphoreHandle_t s_lock;

static void state_lock(void)
{
    if (s_lock != NULL) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
    }
}

static void state_unlock(void)
{
    if (s_lock != NULL) {
        xSemaphoreGive(s_lock);
    }
}

static int64_t now_us(void)
{
    return esp_timer_get_time();
}
#endif

static void reset_capture_buffers_locked(void)
{
    s_state.pre_read = 0;
    s_state.pre_write = 0;
    s_state.pre_count = 0;
    s_state.live_read = 0;
    s_state.live_write = 0;
    s_state.live_count = 0;
}

void audio_session_init(void)
{
#ifndef AUDIO_SESSION_HOST_TEST
    if (s_lock == NULL) {
        s_lock = xSemaphoreCreateMutexStatic(&s_lock_storage);
    }
#endif
    state_lock();
    memset(&s_state, 0, sizeof(s_state));
    state_unlock();
}

bool audio_session_begin_capture(void)
{
    state_lock();
    s_state.generation++;
    if (s_state.generation == 0) {
        s_state.generation = 1;
    }
    s_state.capture_state = CAPTURE_PENDING;
    s_state.capture_active = true;
    s_state.capture_started_us = now_us();
    reset_capture_buffers_locked();

    if (s_state.owner == AUDIO_SESSION_OWNER_TALK) {
        s_state.cancel_talk = true;
    } else if (s_state.owner == AUDIO_SESSION_OWNER_ALERT) {
        /* Revoke before the alert network operation returns. It must check the lease
         * again before touching playback, while capture can proceed immediately. */
        s_state.cancel_alert = true;
        s_state.owner = AUDIO_SESSION_OWNER_NONE;
    }
    state_unlock();
    return true;
}

bool audio_session_confirm_long_press(void)
{
    bool confirmed = false;
    state_lock();
    if (s_state.capture_state == CAPTURE_PENDING && s_state.capture_active) {
        s_state.capture_state = CAPTURE_CONFIRMED;
        confirmed = true;
    }
    state_unlock();
    return confirmed;
}

bool audio_session_cancel_short_press(void)
{
    bool discarded = false;
    state_lock();
    if (s_state.capture_state == CAPTURE_PENDING) {
        s_state.capture_state = CAPTURE_IDLE;
        s_state.capture_active = false;
        reset_capture_buffers_locked();
        discarded = true;
    } else if (s_state.capture_state == CAPTURE_CONFIRMED) {
        /* Keep buffered samples for the HTTP consumer after button release. */
        s_state.capture_active = false;
    }
    state_unlock();
    return discarded;
}

bool audio_session_capture_pending(void)
{
    state_lock();
    bool pending = s_state.capture_state == CAPTURE_PENDING;
    state_unlock();
    return pending;
}

bool audio_session_capture_confirmed(void)
{
    state_lock();
    bool confirmed = s_state.capture_state == CAPTURE_CONFIRMED;
    state_unlock();
    return confirmed;
}

bool audio_session_capture_active(void)
{
    state_lock();
    bool active = s_state.capture_active;
    state_unlock();
    return active;
}

int64_t audio_session_capture_elapsed_us(void)
{
    state_lock();
    int64_t started = s_state.capture_started_us;
    bool active = s_state.capture_active;
    state_unlock();
    return active ? now_us() - started : 0;
}

uint32_t audio_session_capture_generation(void)
{
    state_lock();
    uint32_t generation = s_state.generation;
    state_unlock();
    return generation;
}

size_t audio_session_write_capture(const int16_t *samples, size_t sample_count)
{
    if (samples == NULL || sample_count == 0) {
        return 0;
    }

    state_lock();
    if (!s_state.capture_active || s_state.capture_state == CAPTURE_IDLE) {
        state_unlock();
        return 0;
    }

    int16_t *ring;
    size_t capacity;
    size_t *write_index;
    size_t *count;
    if (s_state.capture_state == CAPTURE_PENDING) {
        ring = s_prebuffer;
        capacity = PREBUFFER_SAMPLES;
        write_index = &s_state.pre_write;
        count = &s_state.pre_count;
    } else {
        ring = s_live_buffer;
        capacity = LIVE_BUFFER_SAMPLES;
        write_index = &s_state.live_write;
        count = &s_state.live_count;
    }

    size_t accepted = 0;
    while (accepted < sample_count && *count < capacity) {
        ring[*write_index] = samples[accepted++];
        *write_index = (*write_index + 1U) % capacity;
        (*count)++;
    }
    state_unlock();
    return accepted;
}

static size_t read_ring_locked(int16_t *destination, size_t max_samples,
                               int16_t *ring, size_t capacity,
                               size_t *read_index, size_t *count)
{
    size_t copied = 0;
    while (copied < max_samples && *count > 0) {
        destination[copied++] = ring[*read_index];
        *read_index = (*read_index + 1U) % capacity;
        (*count)--;
    }
    return copied;
}

size_t audio_session_read_capture(int16_t *samples, size_t max_samples)
{
    if (samples == NULL || max_samples == 0) {
        return 0;
    }

    state_lock();
    if (s_state.capture_state != CAPTURE_CONFIRMED) {
        state_unlock();
        return 0;
    }

    /* This ordering is the contract: every prebuffer sample is consumed once
     * before any live sample becomes visible to the HTTP uploader. */
    size_t copied = read_ring_locked(samples, max_samples,
                                     s_prebuffer, PREBUFFER_SAMPLES,
                                     &s_state.pre_read, &s_state.pre_count);
    if (copied < max_samples) {
        copied += read_ring_locked(samples + copied, max_samples - copied,
                                   s_live_buffer, LIVE_BUFFER_SAMPLES,
                                   &s_state.live_read, &s_state.live_count);
    }
    state_unlock();
    return copied;
}

bool audio_session_capture_has_buffered(void)
{
    state_lock();
    bool buffered = s_state.pre_count > 0 || s_state.live_count > 0;
    state_unlock();
    return buffered;
}

void audio_session_complete_capture(uint32_t generation)
{
    state_lock();
    if (s_state.generation == generation) {
        s_state.capture_state = CAPTURE_IDLE;
        s_state.capture_active = false;
        reset_capture_buffers_locked();
    }
    state_unlock();
}

bool audio_session_acquire_playback(audio_session_owner_t owner)
{
    if (owner == AUDIO_SESSION_OWNER_NONE) {
        return false;
    }

    state_lock();
    bool available = s_state.owner == AUDIO_SESSION_OWNER_NONE;
    if (owner == AUDIO_SESSION_OWNER_ALERT && s_state.capture_state != CAPTURE_IDLE) {
        available = false;
    }
    if (available) {
        s_state.owner = owner;
        if (owner == AUDIO_SESSION_OWNER_TALK) {
            s_state.cancel_talk = false;
        } else {
            s_state.cancel_alert = false;
        }
    }
    state_unlock();
    return available;
}

void audio_session_cancel_alert(void)
{
    state_lock();
    s_state.cancel_alert = true;
    if (s_state.owner == AUDIO_SESSION_OWNER_ALERT) {
        s_state.owner = AUDIO_SESSION_OWNER_NONE;
    }
    state_unlock();
}

bool audio_session_should_cancel(audio_session_owner_t owner)
{
    state_lock();
    bool cancel = owner == AUDIO_SESSION_OWNER_TALK ? s_state.cancel_talk
                  : owner == AUDIO_SESSION_OWNER_ALERT ? s_state.cancel_alert
                  : false;
    state_unlock();
    return cancel;
}

bool audio_session_owner_is(audio_session_owner_t owner)
{
    state_lock();
    bool owned = s_state.owner == owner;
    state_unlock();
    return owned;
}

void audio_session_release(audio_session_owner_t owner)
{
    state_lock();
    if (s_state.owner == owner) {
        s_state.owner = AUDIO_SESSION_OWNER_NONE;
    }
    if (owner == AUDIO_SESSION_OWNER_TALK) {
        s_state.cancel_talk = false;
    } else if (owner == AUDIO_SESSION_OWNER_ALERT) {
        s_state.cancel_alert = false;
    }
    state_unlock();
}
