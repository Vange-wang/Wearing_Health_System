#pragma once
#include <stdint.h>
#include <stdbool.h>

/* HTTP-only identity; the BLE frame stays exactly eight bytes. Caller locks
 * this state with the existing cache mutex. No voice task or network work. */
typedef struct {
    uint64_t generation;
    uint64_t index;
    uint64_t first_received_us;
    uint8_t seq;
    bool connected;
    bool have_seq;
} health_source_t;

typedef enum {
    HEALTH_SOURCE_NEW,
    HEALTH_SOURCE_DUPLICATE,
    HEALTH_SOURCE_AMBIGUOUS,
    HEALTH_SOURCE_DISCONNECTED,
    HEALTH_SOURCE_CAPACITY
} health_source_result_t;

static inline bool health_source_connect(health_source_t *source)
{
    if (source->generation == UINT64_MAX) return false;
    ++source->generation;
    source->connected = true;
    source->have_seq = false;
    source->index = source->first_received_us = 0;
    return true;
}

static inline void health_source_disconnect(health_source_t *source)
{
    source->connected = source->have_seq = false;
}

static inline health_source_result_t health_source_accept(health_source_t *source,
                                                         uint8_t seq, uint64_t now_us)
{
    if (!source->connected) return HEALTH_SOURCE_DISCONNECTED;
    uint64_t index = seq;
    if (source->have_seq) {
        uint8_t difference = (uint8_t)(seq - source->seq);
        if (difference == 0) return HEALTH_SOURCE_DUPLICATE;
        if (difference >= 128) return HEALTH_SOURCE_AMBIGUOUS;
        if (source->index > INT64_MAX - difference) return HEALTH_SOURCE_CAPACITY;
        index = source->index + difference;
    }
    source->index = index;
    source->seq = seq;
    source->have_seq = true;
    source->first_received_us = now_us;
    return HEALTH_SOURCE_NEW;
}

static inline bool health_source_current(const health_source_t *source,
                                        uint64_t generation)
{
    return source->connected && source->generation == generation;
}
