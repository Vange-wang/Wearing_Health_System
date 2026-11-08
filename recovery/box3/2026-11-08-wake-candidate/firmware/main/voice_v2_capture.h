#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define V2_CAPTURE_SEGMENT_SAMPLES 240000U
#define V2_CAPTURE_SLOTS 2U
#define V2_CAPTURE_MAX_SEGMENTS 16U
#define V2_CAPTURE_MAX_SAMPLES 1920000U
typedef enum { V2_SLOT_FREE,V2_SLOT_WRITING,V2_SLOT_SEALED } v2_slot_state_t;
typedef struct {
    int16_t *pcm;
    size_t written,read;
    uint32_t seq,start;
    v2_slot_state_t state;
    bool segment_limit,leased;
} v2_capture_slot_t;
typedef struct {
    v2_capture_slot_t slots[V2_CAPTURE_SLOTS];
    uint32_t generation,next_seq,next_start,revision;
    int filling;
    bool failed,waiting,playing,commit_pending,committing,continuation_pending;
} v2_capture_t;
/* Caller serializes all operations. Backing memory is allocated once in PSRAM. */
void v2_capture_init(v2_capture_t *,int16_t *,int16_t *);
void v2_capture_reset(v2_capture_t *,uint32_t generation);
bool v2_capture_append(v2_capture_t *,const int16_t *,size_t);
bool v2_capture_endpoint(v2_capture_t *);
bool v2_capture_continue(v2_capture_t *);
bool v2_capture_pcm_begin(v2_capture_t *,uint32_t revision);
bool v2_capture_pcm_complete(v2_capture_t *,uint32_t revision,bool success);
bool v2_capture_mark_playing(v2_capture_t *,uint32_t revision);
int v2_capture_acquire(v2_capture_t *);
size_t v2_capture_read(v2_capture_t *,int slot,int16_t *,size_t capacity);
bool v2_capture_release(v2_capture_t *,int slot);
