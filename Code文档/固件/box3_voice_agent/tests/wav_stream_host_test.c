#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "wav_stream.h"

typedef struct {
    uint8_t bytes[64];
    size_t count;
    size_t max_write;
    int calls;
} fake_output_t;

static void put_u16_le(uint8_t *dst, uint16_t value)
{
    dst[0] = (uint8_t)value;
    dst[1] = (uint8_t)(value >> 8);
}

static void put_u32_le(uint8_t *dst, uint32_t value)
{
    dst[0] = (uint8_t)value;
    dst[1] = (uint8_t)(value >> 8);
    dst[2] = (uint8_t)(value >> 16);
    dst[3] = (uint8_t)(value >> 24);
}

static void make_pcm_header(uint8_t header[44], uint32_t data_bytes)
{
    memset(header, 0, 44);
    memcpy(header, "RIFF", 4);
    put_u32_le(header + 4, 36 + data_bytes);
    memcpy(header + 8, "WAVEfmt ", 8);
    put_u32_le(header + 16, 16);
    put_u16_le(header + 20, 1);
    put_u16_le(header + 22, 1);
    put_u32_le(header + 24, 16000);
    put_u32_le(header + 28, 32000);
    put_u16_le(header + 32, 2);
    put_u16_le(header + 34, 16);
    memcpy(header + 36, "data", 4);
    put_u32_le(header + 40, data_bytes);
}

static int fake_write(void *user, const uint8_t *data, size_t length)
{
    fake_output_t *output = (fake_output_t *)user;
    size_t consumed = length < output->max_write ? length : output->max_write;
    assert(output->count + consumed <= sizeof(output->bytes));
    memcpy(output->bytes + output->count, data, consumed);
    output->count += consumed;
    output->calls++;
    return (int)consumed;
}

static bool never_cancel(void *user)
{
    (void)user;
    return false;
}

static wav_stream_result_t begin_valid(wav_stream_t *stream, uint8_t header[44],
                                       uint32_t data_bytes, fake_output_t *output,
                                       int16_t *stereo, size_t stereo_samples)
{
    make_pcm_header(header, data_bytes);
    return wav_stream_begin(stream, header, 44, 44 + data_bytes, 65536,
                            stereo, stereo_samples, fake_write, never_cancel, output);
}

static void test_valid_pcm_and_exact_short_write_retry(void)
{
    wav_stream_t stream;
    uint8_t header[44];
    int16_t stereo[8];
    fake_output_t output = { .max_write = 3 };
    const uint8_t pcm[] = { 0x34, 0x12, 0x78, 0x56 };

    assert(begin_valid(&stream, header, sizeof(pcm), &output, stereo, 8) == WAV_STREAM_OK);
    assert(wav_stream_write(&stream, pcm, sizeof(pcm)) == WAV_STREAM_OK);
    assert(wav_stream_end(&stream) == WAV_STREAM_OK);
    assert(output.calls > 1);
    assert(output.count == 8);
    const uint8_t expected[] = { 0x34, 0x12, 0x34, 0x12, 0x78, 0x56, 0x78, 0x56 };
    assert(memcmp(output.bytes, expected, sizeof(expected)) == 0);
}

static void test_rejects_short_header(void)
{
    wav_stream_t stream;
    uint8_t header[44];
    int16_t stereo[8];
    fake_output_t output = { .max_write = 64 };
    make_pcm_header(header, 4);
    assert(wav_stream_begin(&stream, header, 43, 48, 65536, stereo, 8,
                            fake_write, never_cancel, &output) == WAV_STREAM_BAD_HEADER);
}

static void test_rejects_unsupported_sample_rate(void)
{
    wav_stream_t stream;
    uint8_t header[44];
    int16_t stereo[8];
    fake_output_t output = { .max_write = 64 };
    make_pcm_header(header, 4);
    put_u32_le(header + 24, 8000);
    assert(wav_stream_begin(&stream, header, 44, 48, 65536, stereo, 8,
                            fake_write, never_cancel, &output) == WAV_STREAM_UNSUPPORTED_FORMAT);
}

static void test_rejects_oversized_frame(void)
{
    wav_stream_t stream;
    uint8_t header[44];
    int16_t stereo[8];
    fake_output_t output = { .max_write = 64 };
    make_pcm_header(header, 4);
    assert(wav_stream_begin(&stream, header, 44, WAV_STREAM_MAX_FRAME_BYTES + 1U,
                            65536, stereo, 8, fake_write, never_cancel, &output)
           == WAV_STREAM_FRAME_TOO_LARGE);
}

static void test_interrupted_pcm_is_not_accepted(void)
{
    wav_stream_t stream;
    uint8_t header[44];
    int16_t stereo[8];
    fake_output_t output = { .max_write = 64 };
    const uint8_t half[] = { 0x34, 0x12 };
    assert(begin_valid(&stream, header, 4, &output, stereo, 8) == WAV_STREAM_OK);
    assert(wav_stream_write(&stream, half, sizeof(half)) == WAV_STREAM_OK);
    assert(wav_stream_end(&stream) == WAV_STREAM_TRUNCATED);
}

static void test_duration_and_heap_guards(void)
{
    wav_stream_t stream;
    uint8_t header[44];
    int16_t stereo[8];
    fake_output_t output = { .max_write = 64 };
    const uint32_t too_long = 32000U * 121U;

    make_pcm_header(header, too_long);
    assert(wav_stream_begin(&stream, header, 44, 44 + too_long, 65536,
                            stereo, 8, fake_write, never_cancel, &output)
           == WAV_STREAM_DURATION_TOO_LONG);

    make_pcm_header(header, 4);
    assert(wav_stream_begin(&stream, header, 44, 48,
                            WAV_STREAM_MIN_FREE_HEAP_BYTES - 1U,
                            stereo, 8, fake_write, never_cancel, &output)
           == WAV_STREAM_LOW_HEAP);
}

int main(void)
{
    test_valid_pcm_and_exact_short_write_retry();
    test_rejects_short_header();
    test_rejects_unsupported_sample_rate();
    test_rejects_oversized_frame();
    test_interrupted_pcm_is_not_accepted();
    test_duration_and_heap_guards();
    puts("wav_stream_host_test: PASS");
    return 0;
}
