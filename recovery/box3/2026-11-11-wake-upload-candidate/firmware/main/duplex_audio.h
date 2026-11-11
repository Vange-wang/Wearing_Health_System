#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DUPLEX_AUDIO_SAMPLE_RATE_HZ 16000U
#define DUPLEX_AUDIO_AEC_FRAME_SAMPLES 512U
#define DUPLEX_AUDIO_VAD_FRAME_SAMPLES 160U
#define DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES 4096U

typedef enum {
    DUPLEX_PLAYBACK_ACK_PROTECTED = 0,
    DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE,
} duplex_playback_policy_t;

#ifdef DUPLEX_AUDIO_HOST_TEST
typedef struct {
    bool (*aec_process)(void *context, const int16_t *microphone,
                        const int16_t *reference, int16_t *output,
                        size_t sample_count);
    bool (*vad_process)(void *context, const int16_t *samples,
                        size_t sample_count);
} duplex_audio_test_ops_t;

bool duplex_audio_init_for_test(const duplex_audio_test_ops_t *ops,
                                void *context);
#endif

bool duplex_audio_init(void);
void duplex_audio_deinit(void);
bool duplex_audio_begin_playback(duplex_playback_policy_t policy,
                                 uint32_t generation);
void duplex_audio_end_playback(void);
size_t duplex_audio_push_playback_stereo(const int16_t *samples,
                                         size_t frame_count);
size_t duplex_audio_process_capture_stereo(const int16_t *samples,
                                           size_t frame_count,
                                           int16_t *output,
                                           size_t output_capacity);
/* Interleaved near-mic mono / independently verified hardware reference.
 * The caller must reject missing samples and unverified channel mapping. */
size_t duplex_audio_process_capture_mic_ref(const int16_t *samples,
                                           size_t frame_count,
                                           int16_t *output,
                                           size_t output_capacity);
bool duplex_audio_take_near_speech(uint32_t *generation);
bool duplex_audio_take_barge_in(uint32_t *generation);
void duplex_audio_capture_gap(void);
bool duplex_audio_degraded(void);
typedef struct {
    uint64_t noise_floor;
    uint32_t generation, valid_reference_frames, invalid_reference_frames;
    uint32_t near_candidates;
    bool initialized, degraded;
} duplex_audio_stats_t;
duplex_audio_stats_t duplex_audio_stats(void);

#ifdef __cplusplus
}
#endif
