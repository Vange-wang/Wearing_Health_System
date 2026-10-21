#include "duplex_audio.h"

#include "barge_in_gate.h"

#include <limits.h>
#include <string.h>

#ifndef DUPLEX_AUDIO_HOST_TEST
#include "esp_aec.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_vad.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "sdkconfig.h"
#endif

#define DUPLEX_AUDIO_AEC_FRAME_MS 32
#define DUPLEX_AUDIO_AEC_MODE 5
#define DUPLEX_AUDIO_NOISE_SMOOTHING_SHIFT 5U

_Static_assert(DUPLEX_AUDIO_AEC_FRAME_SAMPLES ==
                   (DUPLEX_AUDIO_SAMPLE_RATE_HZ *
                    DUPLEX_AUDIO_AEC_FRAME_MS) /
                       1000,
               "AEC frame duration and sample count disagree");

typedef struct {
    int16_t reference_fifo[DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES];
    int16_t microphone_frame[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t reference_frame[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t aec_output[DUPLEX_AUDIO_AEC_FRAME_SAMPLES];
    int16_t vad_frame[DUPLEX_AUDIO_VAD_FRAME_SAMPLES];
} duplex_audio_buffers_t;

typedef struct {
    bool initialized;
    bool capture_discontinuous;
    bool playing;
    bool degraded;
    bool near_speech_pending;
    bool near_speech_reported;
    bool barge_pending;
    bool barge_reported;
    duplex_playback_policy_t policy;
    uint32_t generation;
    uint32_t near_speech_generation;
    uint32_t barge_generation;
    duplex_audio_buffers_t *buffers;
    size_t reference_read;
    size_t reference_count;
    size_t aec_frame_count;
    bool reference_frame_invalid;
    size_t vad_frame_count;
    uint64_t noise_floor;
    uint32_t valid_reference_frames, invalid_reference_frames, near_candidates;
#ifdef DUPLEX_AUDIO_HOST_TEST
    duplex_audio_test_ops_t test_ops;
    void *test_context;
#else
    aec_handle_t aec;
    vad_handle_t vad;
#endif
} duplex_audio_state_t;

static duplex_audio_state_t s_state;

_Static_assert(sizeof(duplex_audio_state_t) <= 256U,
               "duplex control state exceeds internal RAM budget");

#ifdef DUPLEX_AUDIO_HOST_TEST
static duplex_audio_buffers_t s_test_buffers;
#else
static const char *const TAG = "duplex_audio";
#endif

#ifndef DUPLEX_AUDIO_HOST_TEST
static StaticSemaphore_t s_process_mutex_storage;
static SemaphoreHandle_t s_process_mutex;
static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;

static void process_lock(void)
{
    if (s_process_mutex != NULL) {
        (void)xSemaphoreTake(s_process_mutex, portMAX_DELAY);
    }
}

static void process_unlock(void)
{
    if (s_process_mutex != NULL) {
        (void)xSemaphoreGive(s_process_mutex);
    }
}

static void state_lock(void)
{
    taskENTER_CRITICAL(&s_state_lock);
}

static void state_unlock(void)
{
    taskEXIT_CRITICAL(&s_state_lock);
}
#else
static void process_lock(void) {}
static void process_unlock(void) {}
static void state_lock(void) {}
static void state_unlock(void) {}
#endif

static int16_t stereo_to_mono(const int16_t *stereo)
{
    return (int16_t)(((int32_t)stereo[0] + (int32_t)stereo[1]) / 2);
}

static uint64_t energy_of(const int16_t *samples, size_t sample_count)
{
    uint64_t energy = 0U;

    for (size_t i = 0U; i < sample_count; ++i) {
        const int64_t sample = samples[i];
        const uint64_t square = (uint64_t)(sample * sample);
        if (UINT64_MAX - energy < square) {
            return UINT64_MAX;
        }
        energy += square;
    }
    return energy;
}

static void clear_processing_buffers(void)
{
    s_state.aec_frame_count = 0U;
    s_state.reference_frame_invalid = false;
    s_state.vad_frame_count = 0U;
    barge_in_gate_reset();
}

static void reset_playback_state_locked(void)
{
    s_state.reference_read = 0U;
    s_state.reference_count = 0U;
    s_state.near_speech_pending = false;
    s_state.near_speech_reported = false;
    s_state.near_speech_generation = 0U;
    s_state.barge_pending = false;
    s_state.barge_reported = false;
    s_state.barge_generation = 0U;
}

static bool run_aec(const int16_t *microphone, const int16_t *reference,
                    int16_t *output)
{
#ifdef DUPLEX_AUDIO_HOST_TEST
    return s_state.test_ops.aec_process(
        s_state.test_context, microphone, reference, output,
        DUPLEX_AUDIO_AEC_FRAME_SAMPLES);
#else
    aec_process(s_state.aec, (int16_t *)microphone, (int16_t *)reference,
                output);
    return true;
#endif
}

static bool run_vad(const int16_t *samples)
{
#ifdef DUPLEX_AUDIO_HOST_TEST
    return s_state.test_ops.vad_process(
        s_state.test_context, samples, DUPLEX_AUDIO_VAD_FRAME_SAMPLES);
#else
    return vad_process(s_state.vad, (int16_t *)samples,
                       DUPLEX_AUDIO_SAMPLE_RATE_HZ, 10) == VAD_SPEECH;
#endif
}

static void update_noise_floor(const int16_t *samples, size_t sample_count)
{
    size_t offset = 0U;
    process_lock();
    if (!s_state.initialized || s_state.playing) {
        process_unlock();
        return;
    }
    while (sample_count - offset >= DUPLEX_AUDIO_VAD_FRAME_SAMPLES) {
        if (run_vad(samples + offset)) {
            offset += DUPLEX_AUDIO_VAD_FRAME_SAMPLES;
            continue;
        }
        const uint64_t measured =
            energy_of(samples + offset, DUPLEX_AUDIO_VAD_FRAME_SAMPLES);
        const uint64_t energy = measured ? measured : 1U;
        state_lock();
        if (s_state.noise_floor == 0U) {
            s_state.noise_floor = energy;
        } else if (energy >= s_state.noise_floor) {
            s_state.noise_floor +=
                (energy - s_state.noise_floor) >>
                DUPLEX_AUDIO_NOISE_SMOOTHING_SHIFT;
        } else {
            s_state.noise_floor -=
                (s_state.noise_floor - energy) >>
                DUPLEX_AUDIO_NOISE_SMOOTHING_SHIFT;
        }
        state_unlock();
        offset += DUPLEX_AUDIO_VAD_FRAME_SAMPLES;
    }
    process_unlock();
}

static void process_vad_samples(const int16_t *samples, size_t sample_count)
{
    for (size_t i = 0U; i < sample_count; ++i) {
        s_state.buffers->vad_frame[s_state.vad_frame_count++] = samples[i];
        if (s_state.vad_frame_count != DUPLEX_AUDIO_VAD_FRAME_SAMPLES) {
            continue;
        }

        const bool vad_speech = run_vad(s_state.buffers->vad_frame);
        const uint64_t near_energy =
            energy_of(s_state.buffers->vad_frame,
                      DUPLEX_AUDIO_VAD_FRAME_SAMPLES);
        const bool candidate = barge_in_gate_process(
            vad_speech, near_energy, s_state.noise_floor);
        state_lock();
        if (candidate && !s_state.degraded && !s_state.near_speech_reported) {
            s_state.near_candidates++;
            s_state.near_speech_pending = true;
            s_state.near_speech_reported = true;
            s_state.near_speech_generation = s_state.generation;
        }
        if (candidate && !s_state.degraded &&
            s_state.policy == DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE &&
            !s_state.barge_reported) {
            s_state.barge_pending = true;
            s_state.barge_reported = true;
            s_state.barge_generation = s_state.generation;
        }
        state_unlock();
        s_state.vad_frame_count = 0U;
    }
}

bool duplex_audio_init(void)
{
    duplex_audio_deinit();
    memset(&s_state, 0, sizeof(s_state));
    barge_in_gate_init();

#ifdef DUPLEX_AUDIO_HOST_TEST
    memset(&s_test_buffers, 0, sizeof(s_test_buffers));
    s_state.buffers = &s_test_buffers;
    s_state.degraded = true;
    return false;
#else
    const size_t internal_before =
        heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    const size_t psram_before =
        heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);

    if (s_process_mutex == NULL) {
        s_process_mutex =
            xSemaphoreCreateMutexStatic(&s_process_mutex_storage);
    }
    if (s_process_mutex == NULL) {
        s_state.degraded = true;
        return false;
    }
    s_state.buffers = heap_caps_calloc(
        1U, sizeof(*s_state.buffers), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (s_state.buffers == NULL) {
        ESP_LOGE(TAG, "fixed buffer allocation failed bytes=%u",
                 (unsigned)sizeof(*s_state.buffers));
        s_state.degraded = true;
        return false;
    }
    heap_caps_malloc_extmem_enable(0U);
    s_state.aec = aec_pro_create(DUPLEX_AUDIO_AEC_FRAME_MS, 1,
                                 DUPLEX_AUDIO_AEC_MODE);
    heap_caps_malloc_extmem_enable(CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL);
    if (s_state.aec == NULL) {
        ESP_LOGE(TAG, "AEC Pro create failed mode=%d internal_free=%u largest=%u",
                 DUPLEX_AUDIO_AEC_MODE,
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL |
                                                   MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(
                     MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        duplex_audio_deinit();
        s_state.degraded = true;
        return false;
    }
    const size_t internal_after =
        heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    const size_t psram_after =
        heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    ESP_LOGI(TAG,
             "AEC Pro allocation mode=%d frame_ms=%d internal_used=%u "
             "psram_used=%u",
             DUPLEX_AUDIO_AEC_MODE, DUPLEX_AUDIO_AEC_FRAME_MS,
             (unsigned)(internal_before - internal_after),
             (unsigned)(psram_before - psram_after));
    s_state.vad = vad_create(VAD_MODE_4);
    if (s_state.vad == NULL) {
        ESP_LOGE(TAG, "VAD create failed mode=4 internal_free=%u largest=%u",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL |
                                                   MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(
                     MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        duplex_audio_deinit();
        s_state.degraded = true;
        return false;
    }
    s_state.initialized = true;
    return true;
#endif
}

void duplex_audio_deinit(void)
{
#ifndef DUPLEX_AUDIO_HOST_TEST
    if (s_process_mutex != NULL) {
        process_lock();
    }
    if (s_state.aec != NULL) {
        aec_destroy(s_state.aec);
    }
    if (s_state.vad != NULL) {
        vad_destroy(s_state.vad);
    }
    if (s_state.buffers != NULL) {
        heap_caps_free(s_state.buffers);
    }
#endif
    memset(&s_state, 0, sizeof(s_state));
#ifndef DUPLEX_AUDIO_HOST_TEST
    if (s_process_mutex != NULL) {
        process_unlock();
    }
#endif
}

#ifdef DUPLEX_AUDIO_HOST_TEST
bool duplex_audio_init_for_test(const duplex_audio_test_ops_t *ops,
                                void *context)
{
    duplex_audio_deinit();
    if (ops == NULL || ops->aec_process == NULL || ops->vad_process == NULL) {
        s_state.degraded = true;
        return false;
    }
    s_state.test_ops = *ops;
    s_state.test_context = context;
    memset(&s_test_buffers, 0, sizeof(s_test_buffers));
    s_state.buffers = &s_test_buffers;
    s_state.initialized = true;
    barge_in_gate_init();
    return true;
}
#endif

bool duplex_audio_begin_playback(duplex_playback_policy_t policy,
                                 uint32_t generation)
{
    if (!s_state.initialized || s_state.capture_discontinuous ||
        (policy != DUPLEX_PLAYBACK_ACK_PROTECTED &&
         policy != DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE)) {
        s_state.degraded = true;
        return false;
    }

    process_lock();
    clear_processing_buffers();
    state_lock();
    reset_playback_state_locked();
    s_state.valid_reference_frames = s_state.invalid_reference_frames = s_state.near_candidates = 0;
    s_state.policy = policy;
    s_state.generation = generation;
    s_state.playing = true;
    s_state.degraded = false;
    state_unlock();
    process_unlock();
    return true;
}

void duplex_audio_end_playback(void)
{
    process_lock();
    state_lock();
    s_state.playing = false;
    s_state.reference_read = 0U;
    s_state.reference_count = 0U;
    state_unlock();
    clear_processing_buffers();
    process_unlock();
}

size_t duplex_audio_push_playback_stereo(const int16_t *samples,
                                         size_t frame_count)
{
    size_t accepted = 0U;

    if (samples == NULL) {
        return 0U;
    }

    state_lock();
    if (!s_state.playing) {
        state_unlock();
        return 0U;
    }
    while (accepted < frame_count &&
           s_state.reference_count < DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES) {
        const size_t write_index =
            (s_state.reference_read + s_state.reference_count) %
            DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES;
        s_state.buffers->reference_fifo[write_index] =
            stereo_to_mono(samples + (accepted * 2U));
        s_state.reference_count++;
        accepted++;
    }
    if (accepted != frame_count) {
        s_state.degraded = true;
        s_state.near_speech_pending = false;
        s_state.barge_pending = false;
    }
    state_unlock();
    return accepted;
}

static size_t process_capture(const int16_t *samples,
                              size_t frame_count,
                              int16_t *output,
                              size_t output_capacity,
                              bool hardware_reference)
{
    size_t produced = 0U;
    bool playing;
    bool degraded;

    if (samples == NULL || output == NULL || output_capacity < frame_count) {
        return 0U;
    }

    state_lock();
    playing = s_state.playing;
    degraded = s_state.degraded;
    state_unlock();
    if (hardware_reference && degraded) return 0U;
    if (!playing || degraded) {
        for (size_t i = 0U; i < frame_count; ++i) {
            output[i] = hardware_reference ? samples[i * 2U] : stereo_to_mono(samples + (i * 2U));
        }
        if (!playing) {
            update_noise_floor(output, frame_count);
        }
        return frame_count;
    }

    process_lock();
    state_lock();
    playing = s_state.playing;
    degraded = s_state.degraded;
    state_unlock();
    if (hardware_reference && degraded) {
        process_unlock();
        return 0U;
    }
    if (!playing || degraded) {
        process_unlock();
        for (size_t i = 0U; i < frame_count; ++i) {
            output[i] = hardware_reference ? samples[i * 2U] : stereo_to_mono(samples + (i * 2U));
        }
        if (!playing) {
            update_noise_floor(output, frame_count);
        }
        return frame_count;
    }

    state_lock();
    for (size_t i = 0U; i < frame_count; ++i) {
        const size_t frame_index = s_state.aec_frame_count++;
        s_state.buffers->microphone_frame[frame_index] =
            hardware_reference ? samples[i * 2U] : stereo_to_mono(samples + (i * 2U));
        if (hardware_reference) {
            s_state.buffers->reference_frame[frame_index] = samples[i * 2U + 1U];
        } else if (s_state.reference_count > 0U) {
            s_state.buffers->reference_frame[frame_index] =
                s_state.buffers->reference_fifo[s_state.reference_read];
            s_state.reference_read =
                (s_state.reference_read + 1U) %
                DUPLEX_AUDIO_REFERENCE_FIFO_SAMPLES;
            s_state.reference_count--;
        } else {
            s_state.buffers->reference_frame[frame_index] = 0;
            /* Missing samples are not a valid silent playback reference.
             * Revoke pending evidence immediately, including partial frames.
             * process_lock serializes this reset with VAD accumulation. */
            if (!s_state.reference_frame_invalid) {
                s_state.reference_frame_invalid = true;
                s_state.vad_frame_count = 0U;
                barge_in_gate_reset();
                s_state.near_speech_pending = false;
                s_state.near_speech_reported = false;
                s_state.barge_pending = false;
                s_state.barge_reported = false;
            }
        }

        if (s_state.aec_frame_count != DUPLEX_AUDIO_AEC_FRAME_SAMPLES) {
            continue;
        }
        state_unlock();

        if (!run_aec(s_state.buffers->microphone_frame,
                     s_state.buffers->reference_frame,
                     s_state.buffers->aec_output)) {
            state_lock();
            s_state.degraded = true;
            s_state.near_speech_pending = false;
            s_state.barge_pending = false;
            state_unlock();
            s_state.aec_frame_count = 0U;
            state_lock();
            break;
        }
        memcpy(output + produced, s_state.buffers->aec_output,
               sizeof(s_state.buffers->aec_output));
        produced += DUPLEX_AUDIO_AEC_FRAME_SAMPLES;
        state_lock();
        if (s_state.reference_frame_invalid) s_state.invalid_reference_frames++;
        else s_state.valid_reference_frames++;
        state_unlock();
        if (!s_state.reference_frame_invalid) {
            process_vad_samples(s_state.buffers->aec_output,
                                DUPLEX_AUDIO_AEC_FRAME_SAMPLES);
        }
        s_state.aec_frame_count = 0U;
        s_state.reference_frame_invalid = false;
        state_lock();
    }
    state_unlock();

    state_lock();
    degraded = s_state.degraded;
    state_unlock();
    if (hardware_reference && degraded) {
        process_unlock();
        return 0U;
    }
    if (degraded) {
        for (size_t i = produced; i < frame_count; ++i) {
            output[i] = hardware_reference ? samples[i * 2U] : stereo_to_mono(samples + (i * 2U));
        }
        process_unlock();
        return frame_count;
    }
    process_unlock();
    return produced;
}

size_t duplex_audio_process_capture_stereo(const int16_t *samples, size_t frames,
                                           int16_t *output, size_t capacity)
{
    return process_capture(samples, frames, output, capacity, false);
}

size_t duplex_audio_process_capture_mic_ref(const int16_t *samples, size_t frames,
                                           int16_t *output, size_t capacity)
{
    return process_capture(samples, frames, output, capacity, true);
}

bool duplex_audio_take_near_speech(uint32_t *generation)
{
    bool taken = false;

    if (generation == NULL) {
        return false;
    }
    state_lock();
    if (s_state.near_speech_pending && !s_state.degraded) {
        *generation = s_state.near_speech_generation;
        s_state.near_speech_pending = false;
        taken = true;
    }
    state_unlock();
    return taken;
}

bool duplex_audio_take_barge_in(uint32_t *generation)
{
    bool taken = false;

    if (generation == NULL) {
        return false;
    }
    state_lock();
    if (s_state.barge_pending && !s_state.degraded) {
        *generation = s_state.barge_generation;
        s_state.barge_pending = false;
        taken = true;
    }
    state_unlock();
    return taken;
}

void duplex_audio_capture_gap(void)
{
    process_lock();
    state_lock();
    s_state.capture_discontinuous = true;
    s_state.degraded = true;
    s_state.playing = false;
    s_state.noise_floor = 0;
    reset_playback_state_locked();
    state_unlock();
    clear_processing_buffers();
    if (s_state.buffers) memset(s_state.buffers, 0, sizeof(*s_state.buffers));
    process_unlock();
    /* The opaque AEC filter has no reset API. Fresh init is mandatory before
     * accepting hardware-reference PCM again; begin_playback cannot bypass it. */
}

bool duplex_audio_degraded(void)
{
    bool degraded;

    state_lock();
    degraded = s_state.degraded;
    state_unlock();
    return degraded;
}

duplex_audio_stats_t duplex_audio_stats(void)
{
    state_lock();
    duplex_audio_stats_t stats = {
        .noise_floor=s_state.noise_floor, .generation=s_state.generation,
        .valid_reference_frames=s_state.valid_reference_frames,
        .invalid_reference_frames=s_state.invalid_reference_frames,
        .near_candidates=s_state.near_candidates,
        .initialized=s_state.initialized, .degraded=s_state.degraded,
    };
    state_unlock();
    return stats;
}
