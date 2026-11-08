#include "wav_stream.h"

#include <string.h>

static uint16_t read_u16_le(const uint8_t *value)
{
    return (uint16_t)value[0] | ((uint16_t)value[1] << 8);
}

static uint32_t read_u32_le(const uint8_t *value)
{
    return (uint32_t)value[0] | ((uint32_t)value[1] << 8) |
           ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
}

static bool stream_cancelled(wav_stream_t *stream)
{
    return stream->cancelled != NULL && stream->cancelled(stream->user);
}

static wav_stream_result_t output_all(wav_stream_t *stream, size_t byte_count)
{
    uint8_t *bytes = (uint8_t *)stream->stereo_buffer;
    size_t offset = 0;
    while (offset < byte_count) {
        if (stream_cancelled(stream)) {
            return WAV_STREAM_CANCELLED;
        }
        int consumed = stream->output(stream->user, bytes + offset, byte_count - offset);
        if (consumed <= 0 || (size_t)consumed > byte_count - offset) {
            return WAV_STREAM_OUTPUT_ERROR;
        }
        offset += (size_t)consumed;
    }
    return WAV_STREAM_OK;
}

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
    void *user)
{
    if (stream == NULL || header == NULL || stereo_buffer == NULL || output == NULL ||
        stereo_sample_capacity < 2) {
        return WAV_STREAM_BAD_ARGUMENT;
    }
    memset(stream, 0, sizeof(*stream));
    if (header_length != WAV_STREAM_HEADER_BYTES) {
        stream->status = WAV_STREAM_BAD_HEADER;
        return stream->status;
    }
    if (frame_length > WAV_STREAM_MAX_FRAME_BYTES) {
        stream->status = WAV_STREAM_FRAME_TOO_LARGE;
        return stream->status;
    }
    if (frame_length < WAV_STREAM_HEADER_BYTES ||
        memcmp(header, "RIFF", 4) != 0 || memcmp(header + 8, "WAVE", 4) != 0 ||
        memcmp(header + 12, "fmt ", 4) != 0 || memcmp(header + 36, "data", 4) != 0 ||
        read_u32_le(header + 16) != 16 ||
        read_u32_le(header + 4) != frame_length - 8U) {
        stream->status = WAV_STREAM_BAD_HEADER;
        return stream->status;
    }

    const uint16_t format = read_u16_le(header + 20);
    const uint16_t channels = read_u16_le(header + 22);
    const uint32_t sample_rate = read_u32_le(header + 24);
    const uint32_t byte_rate = read_u32_le(header + 28);
    const uint16_t block_align = read_u16_le(header + 32);
    const uint16_t bits_per_sample = read_u16_le(header + 34);
    const uint32_t data_bytes = read_u32_le(header + 40);

    if (format != 1 || channels != 1 || sample_rate != 16000 ||
        bits_per_sample != 16 || block_align != 2 || byte_rate != 32000) {
        stream->status = WAV_STREAM_UNSUPPORTED_FORMAT;
        return stream->status;
    }
    if ((data_bytes & 1U) != 0 || data_bytes != frame_length - WAV_STREAM_HEADER_BYTES) {
        stream->status = WAV_STREAM_BAD_HEADER;
        return stream->status;
    }
    uint64_t duration_ms = ((uint64_t)data_bytes * 1000U) / byte_rate;
    if (duration_ms > WAV_STREAM_MAX_DURATION_MS) {
        stream->status = WAV_STREAM_DURATION_TOO_LONG;
        return stream->status;
    }
    if (free_heap_bytes < WAV_STREAM_MIN_FREE_HEAP_BYTES) {
        stream->status = WAV_STREAM_LOW_HEAP;
        return stream->status;
    }

    stream->expected_pcm_bytes = data_bytes;
    stream->sample_rate = sample_rate;
    stream->stereo_buffer = stereo_buffer;
    stream->stereo_sample_capacity = stereo_sample_capacity;
    stream->output = output;
    stream->cancelled = cancelled;
    stream->user = user;
    stream->status = WAV_STREAM_OK;
    stream->active = true;
    return WAV_STREAM_OK;
}

static wav_stream_result_t write_stereo_frames(wav_stream_t *stream,
                                                const uint8_t *pcm,
                                                size_t mono_frames)
{
    for (size_t i = 0; i < mono_frames; ++i) {
        int16_t sample = (int16_t)read_u16_le(pcm + i * 2U);
        stream->stereo_buffer[i * 2U] = sample;
        stream->stereo_buffer[i * 2U + 1U] = sample;
    }
    return output_all(stream, mono_frames * 2U * sizeof(int16_t));
}

wav_stream_result_t wav_stream_write(wav_stream_t *stream,
                                     const uint8_t *pcm,
                                     size_t length)
{
    if (stream == NULL || (!stream->active && stream->status == WAV_STREAM_OK) ||
        (pcm == NULL && length != 0)) {
        return WAV_STREAM_BAD_ARGUMENT;
    }
    if (stream->status != WAV_STREAM_OK) {
        return stream->status;
    }
    if (stream_cancelled(stream)) {
        stream->status = WAV_STREAM_CANCELLED;
        return stream->status;
    }
    if (length > stream->expected_pcm_bytes - stream->received_pcm_bytes) {
        stream->status = WAV_STREAM_DATA_OVERFLOW;
        return stream->status;
    }
    stream->received_pcm_bytes += (uint32_t)length;

    size_t offset = 0;
    if (stream->has_pending_byte && length > 0) {
        uint8_t sample_bytes[2] = { stream->pending_low_byte, pcm[0] };
        wav_stream_result_t result = write_stereo_frames(stream, sample_bytes, 1);
        if (result != WAV_STREAM_OK) {
            stream->status = result;
            return result;
        }
        stream->has_pending_byte = false;
        offset = 1;
    }

    const size_t max_mono_frames = stream->stereo_sample_capacity / 2U;
    while (length - offset >= 2U) {
        size_t frames = (length - offset) / 2U;
        if (frames > max_mono_frames) {
            frames = max_mono_frames;
        }
        wav_stream_result_t result = write_stereo_frames(stream, pcm + offset, frames);
        if (result != WAV_STREAM_OK) {
            stream->status = result;
            return result;
        }
        offset += frames * 2U;
    }
    if (offset < length) {
        stream->pending_low_byte = pcm[offset];
        stream->has_pending_byte = true;
    }
    return WAV_STREAM_OK;
}

wav_stream_result_t wav_stream_end(wav_stream_t *stream)
{
    if (stream == NULL) {
        return WAV_STREAM_BAD_ARGUMENT;
    }
    if (stream->status != WAV_STREAM_OK) {
        stream->active = false;
        return stream->status;
    }
    if (stream_cancelled(stream)) {
        stream->status = WAV_STREAM_CANCELLED;
    } else if (stream->received_pcm_bytes != stream->expected_pcm_bytes ||
               stream->has_pending_byte) {
        stream->status = WAV_STREAM_TRUNCATED;
    }
    stream->active = false;
    return stream->status;
}

const char *wav_stream_result_name(wav_stream_result_t result)
{
    switch (result) {
    case WAV_STREAM_OK: return "ok";
    case WAV_STREAM_BAD_ARGUMENT: return "bad_argument";
    case WAV_STREAM_BAD_HEADER: return "bad_header";
    case WAV_STREAM_UNSUPPORTED_FORMAT: return "unsupported_format";
    case WAV_STREAM_FRAME_TOO_LARGE: return "frame_too_large";
    case WAV_STREAM_DURATION_TOO_LONG: return "duration_too_long";
    case WAV_STREAM_LOW_HEAP: return "low_heap";
    case WAV_STREAM_DATA_OVERFLOW: return "data_overflow";
    case WAV_STREAM_CANCELLED: return "cancelled";
    case WAV_STREAM_OUTPUT_ERROR: return "output_error";
    case WAV_STREAM_TRUNCATED: return "truncated";
    default: return "unknown";
    }
}
