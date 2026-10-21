#include "wake_ack.h"

#include <limits.h>
#include <stdio.h>

static const wake_ack_phrase_t s_phrases[] = {
    { "wozai", "我在", "/spiffs/ack_wozai.wav" },
    { "zala", "咋啦", "/spiffs/ack_zala.wav" },
    { "enna", "嗯呐", "/spiffs/ack_enna.wav" },
    { "dao", "到", "/spiffs/ack_dao.wav" },
    { "laila", "来啦", "/spiffs/ack_laila.wav" },
};

size_t wake_ack_phrase_count(void)
{
    return sizeof(s_phrases) / sizeof(s_phrases[0]);
}

const wake_ack_phrase_t *wake_ack_phrase_at(size_t index)
{
    return index < wake_ack_phrase_count() ? &s_phrases[index] : NULL;
}

size_t wake_ack_select_index(uint32_t random_value, size_t previous_index)
{
    size_t count = wake_ack_phrase_count();
    if (previous_index >= count) {
        return (size_t)(random_value % (uint32_t)count);
    }

    size_t selected = (size_t)(random_value % (uint32_t)(count - 1U));
    return selected >= previous_index ? selected + 1U : selected;
}

static wake_ack_play_result_t map_stream_result(wav_stream_result_t result)
{
    if (result == WAV_STREAM_OK) {
        return WAKE_ACK_PLAY_OK;
    }
    if (result == WAV_STREAM_CANCELLED) {
        return WAKE_ACK_PLAY_CANCELLED;
    }
    if (result == WAV_STREAM_OUTPUT_ERROR) {
        return WAKE_ACK_PLAY_OUTPUT_ERROR;
    }
    if (result == WAV_STREAM_BAD_ARGUMENT) {
        return WAKE_ACK_PLAY_BAD_ARGUMENT;
    }
    return WAKE_ACK_PLAY_INVALID_WAV;
}

wake_ack_play_result_t wake_ack_play_file(
    const char *path,
    uint8_t *read_buffer,
    size_t read_buffer_size,
    int16_t *stereo_buffer,
    size_t stereo_sample_capacity,
    size_t free_heap_bytes,
    wav_stream_output_fn output,
    wav_stream_cancel_fn cancelled,
    void *user)
{
    if (path == NULL || read_buffer == NULL ||
        read_buffer_size < WAV_STREAM_HEADER_BYTES || stereo_buffer == NULL ||
        stereo_sample_capacity == 0U || output == NULL) {
        return WAKE_ACK_PLAY_BAD_ARGUMENT;
    }

    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return WAKE_ACK_PLAY_FILE_ERROR;
    }

    wake_ack_play_result_t result = WAKE_ACK_PLAY_FILE_ERROR;
    if (fseek(file, 0, SEEK_END) != 0) {
        goto cleanup;
    }
    long file_length = ftell(file);
    if (file_length < (long)WAV_STREAM_HEADER_BYTES ||
        (uint64_t)file_length > UINT32_MAX || fseek(file, 0, SEEK_SET) != 0) {
        result = WAKE_ACK_PLAY_INVALID_WAV;
        goto cleanup;
    }

    if (fread(read_buffer, 1U, WAV_STREAM_HEADER_BYTES, file) !=
        WAV_STREAM_HEADER_BYTES) {
        goto cleanup;
    }

    wav_stream_t stream;
    wav_stream_result_t stream_result = wav_stream_begin(
        &stream, read_buffer, WAV_STREAM_HEADER_BYTES, (uint32_t)file_length,
        free_heap_bytes, stereo_buffer, stereo_sample_capacity, output,
        cancelled, user);
    if (stream_result != WAV_STREAM_OK) {
        result = map_stream_result(stream_result);
        goto cleanup;
    }

    result = WAKE_ACK_PLAY_OK;
    while (true) {
        if (cancelled != NULL && cancelled(user)) {
            result = WAKE_ACK_PLAY_CANCELLED;
            break;
        }
        size_t read = fread(read_buffer, 1U, read_buffer_size, file);
        if (read > 0U) {
            stream_result = wav_stream_write(&stream, read_buffer, read);
            if (stream_result != WAV_STREAM_OK) {
                result = map_stream_result(stream_result);
                break;
            }
        }
        if (read < read_buffer_size) {
            if (ferror(file)) {
                result = WAKE_ACK_PLAY_FILE_ERROR;
            }
            break;
        }
    }

    if (result == WAKE_ACK_PLAY_OK) {
        result = map_stream_result(wav_stream_end(&stream));
    }

cleanup:
    fclose(file);
    return result;
}

const char *wake_ack_play_result_name(wake_ack_play_result_t result)
{
    switch (result) {
    case WAKE_ACK_PLAY_OK:
        return "ok";
    case WAKE_ACK_PLAY_BAD_ARGUMENT:
        return "bad_argument";
    case WAKE_ACK_PLAY_FILE_ERROR:
        return "file_error";
    case WAKE_ACK_PLAY_INVALID_WAV:
        return "invalid_wav";
    case WAKE_ACK_PLAY_CANCELLED:
        return "cancelled";
    case WAKE_ACK_PLAY_OUTPUT_ERROR:
        return "output_error";
    default:
        return "unknown";
    }
}
