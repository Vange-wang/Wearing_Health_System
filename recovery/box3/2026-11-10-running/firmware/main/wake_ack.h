#pragma once

#include <stddef.h>
#include <stdint.h>

#include "wav_stream.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *id;
    const char *text;
    const char *path;
} wake_ack_phrase_t;

size_t wake_ack_phrase_count(void);
const wake_ack_phrase_t *wake_ack_phrase_at(size_t index);

/* Selects uniformly from the full catalog for the first round, then uniformly
 * from all entries except previous_index. A previous index outside the catalog
 * means that no prior selection exists. */
size_t wake_ack_select_index(uint32_t random_value, size_t previous_index);

typedef enum {
    WAKE_ACK_PLAY_OK = 0,
    WAKE_ACK_PLAY_BAD_ARGUMENT,
    WAKE_ACK_PLAY_FILE_ERROR,
    WAKE_ACK_PLAY_INVALID_WAV,
    WAKE_ACK_PLAY_CANCELLED,
    WAKE_ACK_PLAY_OUTPUT_ERROR,
} wake_ack_play_result_t;

/* Streams one canonical WAV from storage through the shared mono-to-stereo
 * converter. The caller owns both fixed buffers; this function never loads a
 * complete phrase into memory and performs no heap allocation. */
wake_ack_play_result_t wake_ack_play_file(
    const char *path,
    uint8_t *read_buffer,
    size_t read_buffer_size,
    int16_t *stereo_buffer,
    size_t stereo_sample_capacity,
    size_t free_heap_bytes,
    wav_stream_output_fn output,
    wav_stream_cancel_fn cancelled,
    void *user);

const char *wake_ack_play_result_name(wake_ack_play_result_t result);

#ifdef __cplusplus
}
#endif
