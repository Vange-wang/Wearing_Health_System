#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WAV_STREAM_HEADER_BYTES 44U
#define WAV_STREAM_MAX_FRAME_BYTES (8U * 1024U * 1024U)
#define WAV_STREAM_MAX_DURATION_MS 120000U
#define WAV_STREAM_MIN_FREE_HEAP_BYTES (32U * 1024U)

typedef enum {
    WAV_STREAM_OK = 0,
    WAV_STREAM_BAD_ARGUMENT,
    WAV_STREAM_BAD_HEADER,
    WAV_STREAM_UNSUPPORTED_FORMAT,
    WAV_STREAM_FRAME_TOO_LARGE,
    WAV_STREAM_DURATION_TOO_LONG,
    WAV_STREAM_LOW_HEAP,
    WAV_STREAM_DATA_OVERFLOW,
    WAV_STREAM_CANCELLED,
    WAV_STREAM_OUTPUT_ERROR,
    WAV_STREAM_TRUNCATED,
} wav_stream_result_t;

/* Returns the number of bytes consumed, zero for no progress, or a negative error. */
typedef int (*wav_stream_output_fn)(void *user, const uint8_t *data, size_t length);
typedef bool (*wav_stream_cancel_fn)(void *user);

typedef struct {
    uint32_t expected_pcm_bytes;
    uint32_t received_pcm_bytes;
    uint32_t sample_rate;
    int16_t *stereo_buffer;
    size_t stereo_sample_capacity;
    wav_stream_output_fn output;
    wav_stream_cancel_fn cancelled;
    void *user;
    wav_stream_result_t status;
    uint8_t pending_low_byte;
    bool has_pending_byte;
    bool active;
} wav_stream_t;

wav_stream_result_t wav_stream_begin(
    wav_stream_t *stream,
    const uint8_t *header,
    size_t header_length,
    uint32_t frame_length,
    size_t free_heap_bytes,
    int16_t *stereo_buffer,
    size_t stereo_sample_capacity,
    wav_stream_output_fn output,
    wav_stream_cancel_fn cancelled,
    void *user);

wav_stream_result_t wav_stream_write(
    wav_stream_t *stream,
    const uint8_t *pcm,
    size_t length);

wav_stream_result_t wav_stream_end(wav_stream_t *stream);
const char *wav_stream_result_name(wav_stream_result_t result);

#ifdef __cplusplus
}
#endif
