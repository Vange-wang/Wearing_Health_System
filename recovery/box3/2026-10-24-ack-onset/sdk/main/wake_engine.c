#include "wake_engine.h"

#include <string.h>

#ifndef WAKE_ENGINE_HOST_TEST
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_memory_utils.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "model_path.h"
#endif

#define WAKE_WORD_MODEL "wn9_miaomiaotongxue_tts"
#define SPEECH_THRESHOLD 500
#define TAIL_CONFIRM_LOW_FRAMES 8U
#define TAIL_CONFIRM_MAX_FRAMES 30U
#define FIRST_SPEECH_FRAMES 10U
#define UPLOAD_PRE_ROLL_SAMPLES 3200U
#define NO_SPEECH_SAMPLES 960000U
#define END_LOW_FRAMES 8U
#define RECOVERY_HIGH_FRAMES 6U
#define END_WINDOW_SAMPLES 4800U
#define MAX_CAPTURE_SAMPLES 240000U
#define RESPONSE_NO_PROGRESS_US 30000000LL
#define PRE_ROLL_BUFFER_BYTES \
    (WAKE_ENGINE_PRE_ROLL_SAMPLES * sizeof(int16_t))
#define HOLD_BUFFER_BYTES (WAKE_ENGINE_HOLD_SAMPLES * sizeof(int16_t))
#define WAKE_AUDIO_BUFFER_BYTES (PRE_ROLL_BUFFER_BYTES + HOLD_BUFFER_BYTES)

typedef struct {
    wake_engine_state_t state;
    wake_engine_trigger_mode_t mode;
    uint32_t generation;
    uint32_t events;
    bool begin_pending;
    bool deferred_input;
    bool ack_pending;
    bool ack_speech_detected;
    bool ack_protected;
    bool ack_completion_pending;
    uint32_t tail_low_frames;
    uint32_t tail_total_frames;
    uint32_t first_speech_frames;
    uint32_t wait_samples;
    bool stop_pending;
    uint32_t stop_generation;
    bool stop_cancel_round;
    uint32_t end_low_frames;
    bool end_pending;
    uint32_t end_window_samples;
    uint32_t recovery_high_frames;
    bool hold_flush_ready;
    bool cancel_round;
    uint32_t upload_samples;
    bool duration_stop_set;
    bool unbound_cancel_requested;
    uint64_t pending_ticket;
} wake_state_t;

typedef struct {
    uint32_t generation;
    size_t ring_pending;
    size_t in_flight_bytes;
    size_t framing_pending;
} wake_backlog_t;

static wake_state_t s_state;
/* Never reset on round/init/key changes: stale tickets must not acquire a new owner. */
static uint64_t s_pending_sequence;
static uint64_t next_pending_ticket_locked(void)
{
    if(s_pending_sequence==UINT64_MAX)return 0U; /* No identity reuse at exhaustion. */
    return ++s_pending_sequence;
}
#ifndef WAKE_ENGINE_UNBOUND_TEST_STEP
#define WAKE_ENGINE_UNBOUND_TEST_STEP(x) ((void)0)
#endif
#ifdef VOICE_WAKE_DIAGNOSTICS
static uint32_t s_diag_frames,s_diag_detect_calls,s_diag_model_hits;
#define WDIAG_INC(x) ((void)__atomic_fetch_add(&(x),1U,__ATOMIC_RELAXED))
#else
#define WDIAG_INC(x) ((void)0)
#endif
#ifdef WAKE_ENGINE_HOST_TEST
static int16_t s_pre_roll_storage[WAKE_ENGINE_PRE_ROLL_SAMPLES];
static int16_t s_hold_storage[WAKE_ENGINE_HOLD_SAMPLES];
static int16_t *s_pre_roll = s_pre_roll_storage;
static int16_t *s_hold = s_hold_storage;
#else
static int16_t *s_wake_audio_buffers;
static int16_t *s_pre_roll;
static int16_t *s_hold;
#endif
static size_t s_pre_read;
static size_t s_pre_write;
static size_t s_pre_count;
static size_t s_hold_read;
static size_t s_hold_write;
static size_t s_hold_count;
static wake_backlog_t s_backlog;
static uint64_t s_sample_index;

#ifdef WAKE_ENGINE_HOST_TEST
static wake_engine_test_detector_t s_test_detector;
static void *s_test_detector_context;
static void state_lock(void) {}
static void state_unlock(void) {}
static void pre_roll_lock(void) {}
static void pre_roll_unlock(void) {}
static void hold_lock(void) {}
static void hold_unlock(void) {}
static void backlog_lock(void) {}
static void backlog_unlock(void) {}
#else
static const char *TAG = "wake_engine";
static StaticSemaphore_t s_state_lock_storage;
static StaticSemaphore_t s_pre_roll_lock_storage;
static StaticSemaphore_t s_hold_lock_storage;
static StaticSemaphore_t s_backlog_lock_storage;
static SemaphoreHandle_t s_state_lock;
static SemaphoreHandle_t s_pre_roll_lock;
static SemaphoreHandle_t s_hold_lock;
static SemaphoreHandle_t s_backlog_lock;
static srmodel_list_t *s_models;
static const esp_wn_iface_t *s_wakenet;
static model_iface_data_t *s_wakenet_data;
static int16_t *s_wakenet_input;
static size_t s_wakenet_chunk_samples;
static size_t s_wakenet_input_count;

static void state_lock(void)
{
    if (s_state_lock != NULL) {
        xSemaphoreTake(s_state_lock, portMAX_DELAY);
    }
}

static void state_unlock(void)
{
    if (s_state_lock != NULL) {
        xSemaphoreGive(s_state_lock);
    }
}

static void pre_roll_lock(void)
{
    if (s_pre_roll_lock != NULL) {
        xSemaphoreTake(s_pre_roll_lock, portMAX_DELAY);
    }
}

static void pre_roll_unlock(void)
{
    if (s_pre_roll_lock != NULL) {
        xSemaphoreGive(s_pre_roll_lock);
    }
}

static void hold_lock(void)
{
    if (s_hold_lock != NULL) {
        xSemaphoreTake(s_hold_lock, portMAX_DELAY);
    }
}

static void hold_unlock(void)
{
    if (s_hold_lock != NULL) {
        xSemaphoreGive(s_hold_lock);
    }
}

static void backlog_lock(void)
{
    if (s_backlog_lock != NULL) {
        xSemaphoreTake(s_backlog_lock, portMAX_DELAY);
    }
}

static void backlog_unlock(void)
{
    if (s_backlog_lock != NULL) {
        xSemaphoreGive(s_backlog_lock);
    }
}
#endif

static void clear_pre_roll(void)
{
    pre_roll_lock();
    if (s_pre_roll != NULL) {
        memset(s_pre_roll, 0, PRE_ROLL_BUFFER_BYTES);
    }
    s_pre_read = 0;
    s_pre_write = 0;
    s_pre_count = 0;
    pre_roll_unlock();
}

static void append_pre_roll(const int16_t *samples, size_t sample_count)
{
    pre_roll_lock();
    for (size_t i = 0; i < sample_count; ++i) {
        if (s_pre_count == WAKE_ENGINE_PRE_ROLL_SAMPLES) {
            s_pre_read = (s_pre_read + 1U) % WAKE_ENGINE_PRE_ROLL_SAMPLES;
            s_pre_count--;
        }
        s_pre_roll[s_pre_write] = samples[i];
        s_pre_write = (s_pre_write + 1U) % WAKE_ENGINE_PRE_ROLL_SAMPLES;
        s_pre_count++;
    }
    pre_roll_unlock();
}

static void clear_hold(void)
{
    hold_lock();
    if (s_hold != NULL) {
        memset(s_hold, 0, HOLD_BUFFER_BYTES);
    }
    s_hold_read = 0;
    s_hold_write = 0;
    s_hold_count = 0;
    hold_unlock();
}

static bool append_hold(const int16_t *samples, size_t sample_count)
{
    bool accepted = true;
    hold_lock();
    for (size_t i = 0; i < sample_count; ++i) {
        if (s_hold_count == WAKE_ENGINE_HOLD_SAMPLES) {
            accepted = false;
            break;
        }
        s_hold[s_hold_write] = samples[i];
        s_hold_write = (s_hold_write + 1U) % WAKE_ENGINE_HOLD_SAMPLES;
        s_hold_count++;
    }
    hold_unlock();
    return accepted;
}

static void clear_backlog(void)
{
    backlog_lock();
    memset(&s_backlog, 0, sizeof(s_backlog));
    backlog_unlock();
}

static wake_backlog_t backlog_snapshot(void)
{
    backlog_lock();
    wake_backlog_t snapshot = s_backlog;
    backlog_unlock();
    return snapshot;
}

static void trim_pre_roll_for_upload(void)
{
    pre_roll_lock();
    if (s_pre_count > UPLOAD_PRE_ROLL_SAMPLES) {
        size_t drop = s_pre_count - UPLOAD_PRE_ROLL_SAMPLES;
        s_pre_read = (s_pre_read + drop) % WAKE_ENGINE_PRE_ROLL_SAMPLES;
        s_pre_count = UPLOAD_PRE_ROLL_SAMPLES;
    }
    pre_roll_unlock();
}

static bool s_segmented_input;
void wake_engine_enable_segmented_input(void){s_segmented_input=true;}

static void account_upload_samples(size_t sample_count)
{
    state_lock();
    if (s_state.state == WAKE_ENGINE_STATE_UPLOADING &&
        !s_state.duration_stop_set) {
        const uint32_t limit=s_segmented_input ? 1920000U : MAX_CAPTURE_SAMPLES;
        if (sample_count >= limit - s_state.upload_samples) {
            s_state.upload_samples = limit;
            s_state.duration_stop_set = true;
            s_state.stop_pending = true;
            s_state.stop_generation = s_state.generation;
            s_state.stop_cancel_round = false;
            s_state.events |= WAKE_ENGINE_EVENT_ROUND_TIMEOUT;
        } else {
            s_state.upload_samples += (uint32_t)sample_count;
        }
    }
    state_unlock();
}

static bool speech_above_threshold(const int16_t *samples, size_t sample_count,
                                   int threshold)
{
    uint64_t energy = 0;
    for (size_t i = 0; i < sample_count; ++i) {
        int32_t sample = samples[i];
        energy += (uint64_t)(sample * sample);
    }
    uint64_t threshold_energy =
        (uint64_t)threshold * threshold * sample_count;
    return energy >= threshold_energy;
}

static bool detector_hit(const int16_t *samples, size_t sample_count)
{
#ifdef WAKE_ENGINE_HOST_TEST
    WDIAG_INC(s_diag_detect_calls);
    return s_test_detector != NULL &&
           s_test_detector(samples, sample_count, s_test_detector_context);
#else
    bool hit = false;
    size_t offset = 0;
    while (offset < sample_count) {
        size_t available = s_wakenet_chunk_samples - s_wakenet_input_count;
        size_t copy_count = sample_count - offset;
        if (copy_count > available) {
            copy_count = available;
        }
        memcpy(s_wakenet_input + s_wakenet_input_count, samples + offset,
               copy_count * sizeof(int16_t));
        s_wakenet_input_count += copy_count;
        offset += copy_count;
        if (s_wakenet_input_count == s_wakenet_chunk_samples) {
            WDIAG_INC(s_diag_detect_calls);
            int result = s_wakenet->detect(s_wakenet_data, s_wakenet_input);
            s_wakenet_input_count = 0;
            if (result == WAKENET_DETECTED) {
                hit = true;
                break;
            }
        }
    }
    return hit;
#endif
}

#ifndef WAKE_ENGINE_HOST_TEST
bool wake_engine_init(void)
{
    if (s_state_lock == NULL) {
        s_state_lock = xSemaphoreCreateMutexStatic(&s_state_lock_storage);
    }
    if (s_pre_roll_lock == NULL) {
        s_pre_roll_lock = xSemaphoreCreateMutexStatic(&s_pre_roll_lock_storage);
    }
    if (s_hold_lock == NULL) {
        s_hold_lock = xSemaphoreCreateMutexStatic(&s_hold_lock_storage);
    }
    if (s_backlog_lock == NULL) {
        s_backlog_lock = xSemaphoreCreateMutexStatic(&s_backlog_lock_storage);
    }
    if (s_state_lock == NULL || s_pre_roll_lock == NULL || s_hold_lock == NULL ||
        s_backlog_lock == NULL) {
        ESP_LOGE(TAG, "wake:model_load_failed:lock");
        return false;
    }

    if (s_wake_audio_buffers == NULL) {
        s_wake_audio_buffers = heap_caps_calloc(
            1, WAKE_AUDIO_BUFFER_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    }
    if (s_wake_audio_buffers == NULL ||
        !esp_ptr_external_ram(s_wake_audio_buffers)) {
        if (s_wake_audio_buffers != NULL) {
            heap_caps_free(s_wake_audio_buffers);
        }
        s_wake_audio_buffers = NULL;
        s_pre_roll = NULL;
        s_hold = NULL;
        ESP_LOGE(TAG, "wake:model_load_failed:psram_buffers");
        return false;
    }
    s_pre_roll = s_wake_audio_buffers;
    s_hold = s_wake_audio_buffers + WAKE_ENGINE_PRE_ROLL_SAMPLES;
    ESP_LOGI(TAG,
             "wake_buffers_ready caps=psram total_bytes=%u "
             "pre_roll_bytes=%u hold_bytes=%u",
             (unsigned)WAKE_AUDIO_BUFFER_BYTES,
             (unsigned)PRE_ROLL_BUFFER_BYTES,
             (unsigned)HOLD_BUFFER_BYTES);

    memset(&s_state, 0, sizeof(s_state));
    s_sample_index = 0;
    clear_pre_roll();
    clear_hold();
    clear_backlog();
    s_models = esp_srmodel_init("model");
    if (s_models == NULL) {
        ESP_LOGE(TAG, "wake:model_load_failed:model_partition");
        wake_engine_deinit();
        return false;
    }
    char *model_name = esp_srmodel_filter(s_models, ESP_WN_PREFIX,
                                          WAKE_WORD_MODEL);
    if (model_name == NULL) {
        ESP_LOGE(TAG, "wake:model_load_failed:model_filter");
        wake_engine_deinit();
        return false;
    }
    s_wakenet = esp_wn_handle_from_name(model_name);
    if (s_wakenet == NULL) {
        ESP_LOGE(TAG, "wake:model_load_failed:handle");
        wake_engine_deinit();
        return false;
    }
    s_wakenet_data = s_wakenet->create(model_name, DET_MODE_90);
    if (s_wakenet_data == NULL) {
        ESP_LOGE(TAG, "wake:model_load_failed:create");
        wake_engine_deinit();
        return false;
    }
    int threshold_before_milli = -1, threshold_after_milli = -1;
    int threshold_set = -1;
    if (s_wakenet->get_det_threshold && s_wakenet->set_det_threshold) {
        threshold_before_milli = (int)(s_wakenet->get_det_threshold(
            s_wakenet_data, 1) * 1000.0f + 0.5f);
        threshold_set = s_wakenet->set_det_threshold(s_wakenet_data, 0.620f, 1);
        threshold_after_milli = (int)(s_wakenet->get_det_threshold(
            s_wakenet_data, 1) * 1000.0f + 0.5f);
    }
    ESP_LOGI(TAG, "wake:threshold word=1 before_milli=%d requested_milli=620 set=%d after_milli=%d",
             threshold_before_milli, threshold_set, threshold_after_milli);
    if (s_wakenet->get_samp_rate(s_wakenet_data) != 16000 ||
        s_wakenet->get_channel_num(s_wakenet_data) != 1) {
        ESP_LOGE(TAG, "wake:model_load_failed:format");
        wake_engine_deinit();
        return false;
    }
    int chunk_samples = s_wakenet->get_samp_chunksize(s_wakenet_data);
    if (chunk_samples <= 0 || chunk_samples > 16000) {
        ESP_LOGE(TAG, "wake:model_load_failed:chunksize");
        wake_engine_deinit();
        return false;
    }
    s_wakenet_chunk_samples = (size_t)chunk_samples;
    s_wakenet_input = heap_caps_calloc(s_wakenet_chunk_samples,
                                       sizeof(int16_t),
                                       MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (s_wakenet_input == NULL) {
        ESP_LOGE(TAG, "wake:model_load_failed:buffer");
        wake_engine_deinit();
        return false;
    }
    ESP_LOGI(TAG, "wake model=%s partition=model chunksize=%u", model_name,
             (unsigned)s_wakenet_chunk_samples);
    return true;
}
#else
bool wake_engine_init(void)
{
    return false;
}

bool wake_engine_init_for_test(wake_engine_test_detector_t detector,
                               void *context)
{
    memset(&s_state, 0, sizeof(s_state));
    s_sample_index = 0;
    s_test_detector = detector;
    s_test_detector_context = context;
    clear_pre_roll();
    clear_hold();
    clear_backlog();
    return detector != NULL;
}
#endif

void wake_engine_deinit(void)
{
#ifndef WAKE_ENGINE_HOST_TEST
    if (s_wakenet != NULL && s_wakenet_data != NULL) {
        s_wakenet->destroy(s_wakenet_data);
    }
    s_wakenet_data = NULL;
    s_wakenet = NULL;
    if (s_models != NULL) {
        esp_srmodel_deinit(s_models);
    }
    s_models = NULL;
    if (s_wakenet_input != NULL) {
        heap_caps_free(s_wakenet_input);
    }
    s_wakenet_input = NULL;
    s_wakenet_chunk_samples = 0;
    s_wakenet_input_count = 0;
#else
    s_test_detector = NULL;
    s_test_detector_context = NULL;
#endif
    memset(&s_state, 0, sizeof(s_state));
    s_sample_index = 0;
    clear_pre_roll();
    clear_hold();
    clear_backlog();
#ifndef WAKE_ENGINE_HOST_TEST
    if (s_wake_audio_buffers != NULL) {
        heap_caps_free(s_wake_audio_buffers);
    }
    s_wake_audio_buffers = NULL;
    s_pre_roll = NULL;
    s_hold = NULL;
#endif
}

bool wake_engine_available(void)
{
#ifdef WAKE_ENGINE_HOST_TEST
    return s_test_detector != NULL;
#else
    return s_wakenet != NULL && s_wakenet_data != NULL &&
           s_wakenet_input != NULL && s_pre_roll != NULL && s_hold != NULL;
#endif
}

wake_engine_frame_route_t wake_engine_process_frame(const int16_t *samples,
                                                     size_t sample_count)
{
    if (samples == NULL || sample_count != WAKE_ENGINE_FRAME_SAMPLES ||
        !wake_engine_available()) {
        return WAKE_ENGINE_ROUTE_DROP;
    }

    state_lock();
    s_sample_index += sample_count;
    if(s_state.unbound_cancel_requested && s_state.generation==0 &&
       s_state.mode==WAKE_ENGINE_MODE_WAKE) {
        const uint64_t ticket=s_state.pending_ticket;
        state_unlock();
        WDIAG_INC(s_diag_frames); /* Preserve R13 valid-frame accounting on this cold exit. */
        /* Only the original frame producer clears its unbound wake buffers.
         * A concurrent key owns audio_session's separate ring, never these. */
        WAKE_ENGINE_UNBOUND_TEST_STEP(1);
        clear_pre_roll();clear_hold();clear_backlog();
        WAKE_ENGINE_UNBOUND_TEST_STEP(2);
        state_lock();
        if(s_state.unbound_cancel_requested && s_state.pending_ticket==ticket &&
           s_state.generation==0 && s_state.mode==WAKE_ENGINE_MODE_WAKE) {
            memset(&s_state,0,sizeof(s_state));
            s_state.events=WAKE_ENGINE_EVENT_UNBOUND_CANCELLED;
        }
        const bool key_handover=s_state.mode==WAKE_ENGINE_MODE_KEY && s_state.generation!=0;
        state_unlock();
        return key_handover?WAKE_ENGINE_ROUTE_MAIN:WAKE_ENGINE_ROUTE_DROP;
    }
    wake_engine_state_t state = s_state.state;
    state_unlock();

    WDIAG_INC(s_diag_frames);
    if (state == WAKE_ENGINE_STATE_IDLE) {
        if (!detector_hit(samples, sample_count)) {
            return WAKE_ENGINE_ROUTE_DROP;
        }
        state_lock();
        if (s_state.state == WAKE_ENGINE_STATE_IDLE) {
            WDIAG_INC(s_diag_model_hits);
            s_state.state = WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM;
            s_state.mode = WAKE_ENGINE_MODE_WAKE;
            s_state.generation = 0;
            s_state.begin_pending = true;
            s_state.pending_ticket=next_pending_ticket_locked();s_state.unbound_cancel_requested=false;
            s_state.ack_pending = false;
            s_state.tail_low_frames = 0;
            s_state.tail_total_frames = 0;
            s_state.first_speech_frames = 0;
            s_state.wait_samples = 0;
            s_state.events |= WAKE_ENGINE_EVENT_MODEL_HIT;
            state_unlock();
            clear_pre_roll();
            clear_hold();
            clear_backlog();
            return WAKE_ENGINE_ROUTE_DROP;
        }
        state_unlock();
        return WAKE_ENGINE_ROUTE_DROP;
    }

    if (state == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM) {
        bool below_tail_threshold = !speech_above_threshold(
            samples, sample_count, SPEECH_THRESHOLD / 3);
        bool rejected = false;
        state_lock();
        if (s_state.state == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM &&
            s_state.mode == WAKE_ENGINE_MODE_WAKE) {
            s_state.tail_total_frames++;
            if (below_tail_threshold) {
                s_state.tail_low_frames++;
            } else {
                s_state.tail_low_frames = 0;
            }
            if (s_state.tail_low_frames >= TAIL_CONFIRM_LOW_FRAMES) {
                s_state.state = WAKE_ENGINE_STATE_ACK_PLAYING;
                s_state.ack_protected = true;
                s_state.ack_completion_pending = false;
                s_state.ack_speech_detected = false;
                s_state.ack_pending = true;
                s_state.events |= WAKE_ENGINE_EVENT_TRIGGERED;
            } else if (s_state.tail_total_frames >=
                       TAIL_CONFIRM_MAX_FRAMES) {
                s_state.state = WAKE_ENGINE_STATE_IDLE;
                s_state.begin_pending = false;
                s_state.ack_pending = false;
                s_state.events |= WAKE_ENGINE_EVENT_CANDIDATE_REJECTED;
                if (s_state.generation != 0) {
                    s_state.stop_pending = true;
                    s_state.stop_generation = s_state.generation;
                    s_state.stop_cancel_round = true;
                    s_state.cancel_round = true;
                } else {
                    s_state.mode = WAKE_ENGINE_MODE_NONE;
                }
                rejected = true;
            }
        }
        state_unlock();
        if (rejected) {
            clear_pre_roll();
            clear_hold();
            clear_backlog();
        }
        return WAKE_ENGINE_ROUTE_DROP;
    }

    if (state == WAKE_ENGINE_STATE_ACK_PLAYING) {
        append_pre_roll(samples, sample_count);
        return WAKE_ENGINE_ROUTE_DROP;
    }

    if (state == WAKE_ENGINE_STATE_PLAYING) {
        append_pre_roll(samples, sample_count);
        return WAKE_ENGINE_ROUTE_DROP;
    }

    if (state == WAKE_ENGINE_STATE_UPLOADING) {
        state_lock();
        bool staging=s_state.begin_pending || s_state.deferred_input;
        uint32_t staging_generation=s_state.generation;
        state_unlock();
        if(staging) {
            /* Once speech is confirmed, never roll away its first samples
             * while the old response unwinds. Capacity failure is explicit. */
            pre_roll_lock();
            bool fits=sample_count<=WAKE_ENGINE_PRE_ROLL_SAMPLES-s_pre_count;
            if(fits)for(size_t i=0;i<sample_count;i++) {
                s_pre_roll[s_pre_write]=samples[i];
                s_pre_write=(s_pre_write+1U)%WAKE_ENGINE_PRE_ROLL_SAMPLES;
                s_pre_count++;
            }
            pre_roll_unlock();
            if(!fits) {
                if(staging_generation)wake_engine_report_capture_overflow(staging_generation);
                else {
                    state_lock();
                    s_state.begin_pending=false;s_state.deferred_input=false;
                    s_state.state=WAKE_ENGINE_STATE_WAIT_SPEECH;
                    s_state.first_speech_frames=0;s_state.wait_samples=0;
                    s_state.events|=WAKE_ENGINE_EVENT_BUFFER_OVERFLOW;
                    state_unlock();clear_pre_roll();
                }
            }
            return WAKE_ENGINE_ROUTE_DROP;
        }
        account_upload_samples(sample_count);
        state_lock();
        wake_engine_trigger_mode_t mode = s_state.mode;
        bool end_pending = s_state.end_pending;
        state_unlock();
        if (mode == WAKE_ENGINE_MODE_KEY) {
            return WAKE_ENGINE_ROUTE_MAIN;
        }
        if (mode != WAKE_ENGINE_MODE_WAKE) {
            return WAKE_ENGINE_ROUTE_DROP;
        }

        if (end_pending) {
            if (!append_hold(samples, sample_count)) {
                wake_engine_report_capture_overflow(wake_engine_generation());
                clear_hold();
                return WAKE_ENGINE_ROUTE_DROP;
            }
            bool recovered = false;
            bool window_full = false;
            uint32_t generation = 0;
            state_lock();
            if (s_state.state == WAKE_ENGINE_STATE_UPLOADING &&
                s_state.mode == WAKE_ENGINE_MODE_WAKE && s_state.end_pending) {
                s_state.end_window_samples += (uint32_t)sample_count;
                generation = s_state.generation;
                if (speech_above_threshold(samples, sample_count,
                                           SPEECH_THRESHOLD)) {
                    s_state.recovery_high_frames++;
                } else {
                    s_state.recovery_high_frames = 0;
                }
                window_full = s_state.end_window_samples >= END_WINDOW_SAMPLES;
                if (!window_full &&
                    s_state.recovery_high_frames >= RECOVERY_HIGH_FRAMES) {
                    s_state.end_pending = false;
                    s_state.end_low_frames = 0;
                    s_state.hold_flush_ready = true;
                    s_state.events |= WAKE_ENGINE_EVENT_SPEECH_CONTINUE;
                    recovered = true;
                }
            }
            state_unlock();
            if (window_full) {
#ifndef WAKE_ENGINE_HOST_TEST
                wake_backlog_t snapshot = backlog_snapshot();
                ESP_LOGI(TAG,
                         "wake:backlog(ring=%u,in_flight=%u,framing=%u) generation=%u",
                         (unsigned)snapshot.ring_pending,
                         (unsigned)snapshot.in_flight_bytes,
                         (unsigned)snapshot.framing_pending,
                         (unsigned)generation);
#endif
                state_lock();
                if (s_state.state == WAKE_ENGINE_STATE_UPLOADING &&
                    s_state.mode == WAKE_ENGINE_MODE_WAKE &&
                    s_state.generation == generation && s_state.end_pending) {
                    s_state.end_pending = false;
                    s_state.stop_pending = true;
                    s_state.stop_generation = generation;
                    /* Stop the producer, but keep the HTTP round alive so the
                     * consumer can drain transient ring/in-flight/framing
                     * backlog and send the terminating zero chunk. A genuine
                     * transport stall is still bounded by the HTTP timeout. */
                    s_state.stop_cancel_round = false;
                    s_state.cancel_round = false;
                    s_state.events |= WAKE_ENGINE_EVENT_SPEECH_END;
                }
                state_unlock();
                clear_hold();
            }
            (void)recovered;
            return WAKE_ENGINE_ROUTE_HOLD;
        }

        bool below_end_threshold = !speech_above_threshold(
            samples, sample_count, SPEECH_THRESHOLD / 3);
        state_lock();
        if (s_state.state == WAKE_ENGINE_STATE_UPLOADING &&
            s_state.mode == WAKE_ENGINE_MODE_WAKE && !s_state.end_pending) {
            if (below_end_threshold) {
                s_state.end_low_frames++;
            } else {
                s_state.end_low_frames = 0;
            }
            if (s_state.end_low_frames >= END_LOW_FRAMES) {
                s_state.end_pending = true;
                s_state.end_window_samples = 0;
                s_state.recovery_high_frames = 0;
                s_state.events |= WAKE_ENGINE_EVENT_SPEECH_END_PENDING;
            }
        }
        state_unlock();
        return WAKE_ENGINE_ROUTE_MAIN;
    }

    if (state != WAKE_ENGINE_STATE_WAIT_SPEECH) {
        return WAKE_ENGINE_ROUTE_DROP;
    }

    append_pre_roll(samples, sample_count);
    bool above = speech_above_threshold(samples, sample_count,
                                        SPEECH_THRESHOLD);
    bool started = false;
    bool timed_out = false;
    state_lock();
    if (s_state.state == WAKE_ENGINE_STATE_WAIT_SPEECH) {
        s_state.wait_samples += (uint32_t)sample_count;
        if (above) {
            s_state.first_speech_frames++;
        } else {
            s_state.first_speech_frames = 0;
        }
        if (s_state.first_speech_frames >= FIRST_SPEECH_FRAMES) {
            s_state.state = WAKE_ENGINE_STATE_UPLOADING;
            if (s_state.generation == 0U) {
                s_state.begin_pending = true;
                s_state.pending_ticket=next_pending_ticket_locked();s_state.unbound_cancel_requested=false;
            }
            s_state.upload_samples =
                FIRST_SPEECH_FRAMES * WAKE_ENGINE_FRAME_SAMPLES;
            s_state.events |= WAKE_ENGINE_EVENT_SPEECH_START;
            started = true;
        } else if (s_state.wait_samples >= NO_SPEECH_SAMPLES) {
            s_state.state = WAKE_ENGINE_STATE_IDLE;
            s_state.mode = WAKE_ENGINE_MODE_NONE;
            s_state.events |= WAKE_ENGINE_EVENT_NO_SPEECH_TIMEOUT |
                              WAKE_ENGINE_EVENT_SESSION_TIMEOUT;
            s_state.begin_pending = false;
            if (s_state.generation != 0) {
                s_state.stop_pending = true;
                s_state.stop_generation = s_state.generation;
                s_state.stop_cancel_round = false;
            }
            timed_out = true;
        }
    }
    state_unlock();
    if (started) {
        trim_pre_roll_for_upload();
    } else if (timed_out) {
        clear_pre_roll();
    }
    return WAKE_ENGINE_ROUTE_DROP;
}

wake_engine_state_t wake_engine_state(void)
{
    state_lock();
    wake_engine_state_t state = s_state.state;
    state_unlock();
    return state;
}

wake_engine_trigger_mode_t wake_engine_trigger_mode(void)
{
    state_lock();
    wake_engine_trigger_mode_t mode = s_state.mode;
    state_unlock();
    return mode;
}

uint32_t wake_engine_generation(void)
{
    state_lock();
    uint32_t generation = s_state.generation;
    state_unlock();
    return generation;
}

uint64_t wake_engine_sample_index(void)
{
    state_lock();
    uint64_t sample_index = s_sample_index;
    state_unlock();
    return sample_index;
}

uint32_t wake_engine_take_events(void)
{
    state_lock();
    uint32_t events = s_state.events;
    s_state.events = 0;
    state_unlock();
    return events;
}

bool wake_engine_capture_begin_pending(void)
{
    state_lock();
    bool pending = (s_state.state == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM ||
                    s_state.state == WAKE_ENGINE_STATE_ACK_PLAYING ||
                    s_state.state == WAKE_ENGINE_STATE_WAIT_SPEECH ||
                    s_state.state == WAKE_ENGINE_STATE_UPLOADING) &&
                   s_state.mode == WAKE_ENGINE_MODE_WAKE &&
                   s_state.begin_pending;
    state_unlock();
    return pending;
}

bool wake_engine_bind_capture(uint32_t generation)
{
    bool bound = false;
    state_lock();
    if (generation != 0 && s_state.mode == WAKE_ENGINE_MODE_WAKE &&
        (s_state.state == WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM ||
         s_state.state == WAKE_ENGINE_STATE_ACK_PLAYING ||
         s_state.state == WAKE_ENGINE_STATE_WAIT_SPEECH ||
         s_state.state == WAKE_ENGINE_STATE_UPLOADING) &&
        s_state.begin_pending && s_state.generation == 0) {
        s_state.generation = generation;
        s_state.pending_ticket=0;s_state.unbound_cancel_requested=false;
        s_state.begin_pending = false;
        bound = true;
    }
    state_unlock();
    return bound;
}

bool wake_engine_take_ack_request(uint32_t *generation)
{
    if (generation == NULL) {
        return false;
    }
    state_lock();
    bool pending = s_state.state == WAKE_ENGINE_STATE_ACK_PLAYING &&
                   s_state.mode == WAKE_ENGINE_MODE_WAKE &&
                   !s_state.begin_pending && s_state.generation != 0 &&
                   s_state.ack_pending;
    if (pending) {
        *generation = s_state.generation;
        s_state.ack_pending = false;
    }
    state_unlock();
    return pending;
}

bool wake_engine_ack_protected(uint32_t generation)
{
    state_lock();
    bool active = generation != 0 && s_state.generation == generation &&
                  s_state.mode == WAKE_ENGINE_MODE_WAKE && s_state.ack_protected;
    state_unlock();
    return active;
}

/* Playback task publishes completion only. The PCM producer owns buffer cleanup. */
void wake_engine_ack_playback_done(uint32_t generation)
{
    state_lock();
    if (generation != 0 && s_state.generation == generation && s_state.ack_protected) {
        s_state.ack_protected = false;
        s_state.ack_completion_pending = true;
    }
    state_unlock();
}

bool wake_engine_ack_completion_pending(uint32_t generation)
{
    state_lock();
    bool pending = generation != 0 && s_state.generation == generation &&
                   s_state.ack_completion_pending;
    state_unlock();
    return pending;
}

/* PCM producer only, after the entire AEC batch has entered pre-roll.
 * Admission keeps the available onset; subsequent PCM goes to the existing V2 store. */
bool wake_engine_note_ack_speech(uint32_t generation)
{
    bool accepted = false;
    state_lock();
    if (generation != 0 && s_state.generation == generation &&
        s_state.mode == WAKE_ENGINE_MODE_WAKE && !s_state.ack_speech_detected &&
        (s_state.ack_protected || s_state.ack_completion_pending) &&
        s_state.state == WAKE_ENGINE_STATE_ACK_PLAYING && !s_state.cancel_round) {
        s_state.ack_speech_detected = true;
        s_state.state = WAKE_ENGINE_STATE_UPLOADING;
        s_state.events |= WAKE_ENGINE_EVENT_SPEECH_START;
        accepted = true;
    }
    state_unlock();
    return accepted;
}

/* PCM producer only. Never reset an already admitted input or its endpoint. */
bool wake_engine_ack_complete(uint32_t generation)
{
    bool completed = false, empty = false;
    state_lock();
    if (generation != 0 && s_state.generation == generation &&
        s_state.mode == WAKE_ENGINE_MODE_WAKE &&
        (s_state.ack_protected || s_state.ack_completion_pending)) {
        s_state.ack_protected = false;
        s_state.ack_completion_pending = false;
        s_state.ack_pending = false;
        empty = !s_state.ack_speech_detected &&
                s_state.state == WAKE_ENGINE_STATE_ACK_PLAYING;
        if (empty) {
            s_state.state = WAKE_ENGINE_STATE_WAIT_SPEECH;
            s_state.first_speech_frames = 0;
            s_state.wait_samples = 0;
        }
        s_state.events |= WAKE_ENGINE_EVENT_ACK_COMPLETE;
        completed = true;
    }
    state_unlock();
    if (empty) { clear_pre_roll(); clear_hold(); clear_backlog(); }
    return completed;
}

void wake_engine_begin_key(uint32_t generation)
{
    if (generation == 0) {
        return;
    }
    state_lock();
    bool interrupted_wake = s_state.mode == WAKE_ENGINE_MODE_WAKE &&
                            s_state.state != WAKE_ENGINE_STATE_IDLE;
    s_state.state = WAKE_ENGINE_STATE_UPLOADING;
    s_state.mode = WAKE_ENGINE_MODE_KEY;
    s_state.generation = generation;
    s_state.pending_ticket=0;s_state.unbound_cancel_requested=false;
    s_state.begin_pending = false;
    s_state.ack_pending = false;
    s_state.ack_protected = false;
    s_state.ack_completion_pending = false;
    s_state.ack_speech_detected = false;
    s_state.tail_low_frames = 0;
    s_state.tail_total_frames = 0;
    s_state.first_speech_frames = 0;
    s_state.wait_samples = 0;
    s_state.end_low_frames = 0;
    s_state.end_pending = false;
    s_state.end_window_samples = 0;
    s_state.recovery_high_frames = 0;
    s_state.hold_flush_ready = false;
    s_state.cancel_round = false;
    s_state.upload_samples = 0;
    s_state.duration_stop_set = false;
    s_state.stop_pending = false;
    s_state.events = interrupted_wake
                         ? WAKE_ENGINE_EVENT_CANCELLED_BY_KEY
                         : 0U;
    state_unlock();
    clear_pre_roll();
    clear_hold();
    clear_backlog();
}

bool wake_engine_wait_candidate(uint32_t generation)
{
    state_lock();
    bool ok=generation!=0 && s_state.generation==generation &&
        s_state.state==WAKE_ENGINE_STATE_UPLOADING;
    if(ok && s_state.mode==WAKE_ENGINE_MODE_WAKE) {
        s_state.state=WAKE_ENGINE_STATE_WAIT_SPEECH;
        s_state.first_speech_frames=0;s_state.wait_samples=0;
        s_state.end_low_frames=0;s_state.end_pending=false;
        s_state.end_window_samples=0;s_state.recovery_high_frames=0;
    }
    state_unlock();
    if(ok){clear_pre_roll();clear_hold();}
    return ok;
}

bool wake_engine_mark_playing(uint32_t generation)
{
    bool changed = false;
    state_lock();
    if (generation != 0 && s_state.generation == generation &&
        (s_state.state == WAKE_ENGINE_STATE_UPLOADING ||
         (s_segmented_input && s_state.state == WAKE_ENGINE_STATE_WAIT_SPEECH))) {
        s_state.state = WAKE_ENGINE_STATE_PLAYING;
        changed = true;
    }
    state_unlock();
    return changed;
}

bool wake_engine_admit_output(uint32_t generation,bool (*admit)(void *),void *context)
{
    state_lock();
    bool eligible=generation && s_state.generation==generation && !s_state.cancel_round &&
        (s_state.state==WAKE_ENGINE_STATE_WAIT_SPEECH ||
         (s_state.mode==WAKE_ENGINE_MODE_KEY && s_state.state==WAKE_ENGINE_STATE_UPLOADING));
    bool accepted=eligible && admit && admit(context);
    state_unlock();return accepted;
}
int wake_engine_commit_output(uint32_t generation,bool success)
{
    state_lock();
    int result=0;
    if(generation && s_state.generation==generation) {
        if(s_state.mode==WAKE_ENGINE_MODE_WAKE && s_state.state==WAKE_ENGINE_STATE_UPLOADING) {
            s_state.deferred_input=true;result=2;
        }else if(success && (s_state.state==WAKE_ENGINE_STATE_WAIT_SPEECH ||
                              s_state.state==WAKE_ENGINE_STATE_UPLOADING)) {
            s_state.state=WAKE_ENGINE_STATE_PLAYING;result=1;
        }
    }
    state_unlock();return result;
}
bool wake_engine_defer_input(uint32_t generation)
{
    state_lock();
    bool ok=generation && s_state.generation==generation &&
        s_state.state==WAKE_ENGINE_STATE_UPLOADING && s_state.mode==WAKE_ENGINE_MODE_WAKE;
    if(ok)s_state.deferred_input=true;
    state_unlock();return ok;
}
bool wake_engine_restart_deferred_input(uint32_t generation)
{
    state_lock();
    bool ok=generation && s_state.generation==generation && s_state.deferred_input;
    if(ok) {
        s_state.state=WAKE_ENGINE_STATE_UPLOADING;
        s_state.generation=0;s_state.begin_pending=true;s_state.deferred_input=false;
        s_state.pending_ticket=next_pending_ticket_locked();s_state.unbound_cancel_requested=false;
        s_state.cancel_round=false;s_state.stop_pending=false;s_state.end_pending=false;
        s_state.end_low_frames=0;s_state.upload_samples=0;s_state.duration_stop_set=false;
        s_state.events|=WAKE_ENGINE_EVENT_BARGE_IN;
    }
    state_unlock();return ok;
}
bool wake_engine_note_barge_in(uint32_t generation)
{
    bool accepted = false;

    state_lock();
    if (generation != 0U && generation == s_state.generation &&
        s_state.mode == WAKE_ENGINE_MODE_WAKE &&
        s_state.state == WAKE_ENGINE_STATE_PLAYING) {
        s_state.state = WAKE_ENGINE_STATE_UPLOADING;
        s_state.generation = 0U;
        s_state.begin_pending = true;
        s_state.pending_ticket=next_pending_ticket_locked();s_state.unbound_cancel_requested=false;
        s_state.ack_pending = false;
        s_state.first_speech_frames = 0U;
        s_state.wait_samples = 0U;
        s_state.stop_pending = false;
        s_state.stop_generation = 0U;
        s_state.stop_cancel_round = false;
        s_state.end_low_frames = 0U;
        s_state.end_pending = false;
        s_state.end_window_samples = 0U;
        s_state.recovery_high_frames = 0U;
        s_state.hold_flush_ready = false;
        s_state.cancel_round = false;
        s_state.upload_samples = 0U;
        s_state.duration_stop_set = false;
        s_state.events |= WAKE_ENGINE_EVENT_BARGE_IN;
        accepted = true;
    }
    state_unlock();

    if (accepted) {
        trim_pre_roll_for_upload();
        clear_hold();
        clear_backlog();
    }
    return accepted;
}

bool wake_engine_finish_round(uint32_t generation, bool keep_session)
{
    bool finished = false;
    state_lock();
    if (generation != 0 && s_state.generation == generation) {
        const bool rearm = keep_session &&
                           s_state.mode == WAKE_ENGINE_MODE_WAKE;
#ifndef WAKE_ENGINE_HOST_TEST
        s_wakenet_input_count = 0;
        if (s_wakenet_input != NULL) {
            memset(s_wakenet_input, 0,
                   s_wakenet_chunk_samples * sizeof(int16_t));
        }
#endif
        memset(&s_state, 0, sizeof(s_state));
        if (rearm) {
            s_state.state = WAKE_ENGINE_STATE_WAIT_SPEECH;
            s_state.mode = WAKE_ENGINE_MODE_WAKE;
            s_state.events = WAKE_ENGINE_EVENT_SESSION_REARMED;
        }
        finished = true;
    }
    state_unlock();
    if (finished) {
        clear_pre_roll();
        clear_hold();
        clear_backlog();
    }
    return finished;
}

void wake_engine_note_capture_samples(uint32_t generation,
                                      size_t sample_count)
{
    state_lock();
    s_sample_index += sample_count;
    bool current = generation != 0 && s_state.generation == generation &&
                   s_state.state == WAKE_ENGINE_STATE_UPLOADING;
    state_unlock();
    if (current) {
        account_upload_samples(sample_count);
    }
}

void wake_engine_report_capture_overflow(uint32_t generation)
{
    state_lock();
    if (generation != 0 && s_state.generation == generation &&
        s_state.state == WAKE_ENGINE_STATE_UPLOADING) {
        s_state.stop_pending = true;
        s_state.stop_generation = generation;
        s_state.stop_cancel_round = true;
        s_state.cancel_round = true;
        s_state.events |= WAKE_ENGINE_EVENT_BUFFER_OVERFLOW;
    }
    state_unlock();
}

void wake_engine_cancel_key_capture(uint32_t generation)
{
    bool cancelled = false;
    state_lock();
    if (generation != 0 && s_state.generation == generation &&
        s_state.mode == WAKE_ENGINE_MODE_KEY) {
        s_state.state = WAKE_ENGINE_STATE_IDLE;
        s_state.mode = WAKE_ENGINE_MODE_NONE;
        s_state.generation = 0;
        s_state.cancel_round = false;
        cancelled = true;
    }
    state_unlock();
    if (cancelled) {
        clear_pre_roll();
        clear_hold();
        clear_backlog();
    }
}

bool wake_engine_take_stop_request(uint32_t *generation, bool *cancel_round)
{
    if (generation == NULL || cancel_round == NULL) {
        return false;
    }
    state_lock();
    bool pending = s_state.stop_pending;
    if (pending) {
        *generation = s_state.stop_generation;
        *cancel_round = s_state.stop_cancel_round;
        s_state.stop_pending = false;
        s_state.stop_generation = 0;
        s_state.stop_cancel_round = false;
    }
    state_unlock();
    return pending;
}

void wake_engine_set_backlog(uint32_t generation, size_t ring_pending,
                             size_t in_flight_bytes, size_t framing_pending)
{
    if (generation == 0) {
        return;
    }
    state_lock();
    bool current = s_state.generation == generation &&
                   s_state.state == WAKE_ENGINE_STATE_UPLOADING;
    state_unlock();
    if (!current) {
        return;
    }
    backlog_lock();
    s_backlog.generation = generation;
    s_backlog.ring_pending = ring_pending;
    s_backlog.in_flight_bytes = in_flight_bytes;
    s_backlog.framing_pending = framing_pending;
    backlog_unlock();
}

void wake_engine_set_ring_pending(uint32_t generation, size_t ring_pending)
{
    if (generation == 0) {
        return;
    }
    state_lock();
    bool current = s_state.generation == generation &&
                   s_state.state == WAKE_ENGINE_STATE_UPLOADING;
    state_unlock();
    if (!current) {
        return;
    }
    backlog_lock();
    s_backlog.generation = generation;
    s_backlog.ring_pending = ring_pending;
    backlog_unlock();
}

void wake_engine_set_transport_backlog(uint32_t generation,
                                       size_t in_flight_bytes,
                                       size_t framing_pending)
{
    if (generation == 0) {
        return;
    }
    state_lock();
    bool current = s_state.generation == generation &&
                   s_state.state == WAKE_ENGINE_STATE_UPLOADING;
    state_unlock();
    if (!current) {
        return;
    }
    backlog_lock();
    s_backlog.generation = generation;
    s_backlog.in_flight_bytes = in_flight_bytes;
    s_backlog.framing_pending = framing_pending;
    backlog_unlock();
}

bool wake_engine_should_cancel(uint32_t generation)
{
    if (generation == 0) {
        return true;
    }
    state_lock();
    bool cancel = s_state.generation != generation || s_state.cancel_round;
    state_unlock();
    return cancel;
}

size_t wake_engine_read_pre_roll(int16_t *samples, size_t max_samples,
                                 uint32_t generation)
{
    if (samples == NULL || max_samples == 0 || generation == 0) {
        return 0;
    }
    state_lock();
    bool allowed = s_state.state == WAKE_ENGINE_STATE_UPLOADING &&
                   s_state.mode == WAKE_ENGINE_MODE_WAKE &&
                   s_state.generation == generation;
    state_unlock();
    if (!allowed) {
        return 0;
    }

    pre_roll_lock();
    size_t copied = 0;
    while (copied < max_samples && s_pre_count > 0) {
        samples[copied++] = s_pre_roll[s_pre_read];
        s_pre_roll[s_pre_read] = 0;
        s_pre_read = (s_pre_read + 1U) % WAKE_ENGINE_PRE_ROLL_SAMPLES;
        s_pre_count--;
    }
    pre_roll_unlock();
    return copied;
}

size_t wake_engine_read_hold(int16_t *samples, size_t max_samples,
                             uint32_t generation)
{
    if (samples == NULL || max_samples == 0 || generation == 0) {
        return 0;
    }
    state_lock();
    bool allowed = s_state.state == WAKE_ENGINE_STATE_UPLOADING &&
                   s_state.mode == WAKE_ENGINE_MODE_WAKE &&
                   s_state.generation == generation &&
                   s_state.hold_flush_ready;
    state_unlock();
    if (!allowed) {
        return 0;
    }

    hold_lock();
    size_t copied = 0;
    while (copied < max_samples && s_hold_count > 0) {
        samples[copied++] = s_hold[s_hold_read];
        s_hold[s_hold_read] = 0;
        s_hold_read = (s_hold_read + 1U) % WAKE_ENGINE_HOLD_SAMPLES;
        s_hold_count--;
    }
    bool empty = s_hold_count == 0;
    hold_unlock();
    if (empty) {
        state_lock();
        if (s_state.generation == generation) {
            s_state.hold_flush_ready = false;
        }
        state_unlock();
    }
    return copied;
}

void wake_response_progress_init(wake_response_progress_t *progress,
                                 int64_t now_us)
{
    if (progress != NULL) {
        progress->last_progress_us = now_us;
    }
}

wake_response_result_t wake_response_classify(
    wake_response_progress_t *progress, int read_result, int eagain_result,
    bool protocol_complete, int64_t now_us)
{
    if (progress == NULL) {
        return WAKE_RESPONSE_HARD_ERROR;
    }
    if (read_result > 0) {
        progress->last_progress_us = now_us;
        return WAKE_RESPONSE_DATA;
    }
    if (read_result == eagain_result) {
        return now_us - progress->last_progress_us >= RESPONSE_NO_PROGRESS_US
                   ? WAKE_RESPONSE_TIMEOUT
                   : WAKE_RESPONSE_AGAIN;
    }
    if (read_result == 0) {
        return protocol_complete ? WAKE_RESPONSE_COMPLETE_EOF
                                 : WAKE_RESPONSE_TRUNCATED_EOF;
    }
    return WAKE_RESPONSE_HARD_ERROR;
}

bool wake_engine_unbound_request(uint64_t *ticket)
{
    if(ticket==NULL)return false;
    state_lock();
    bool pending=s_state.mode==WAKE_ENGINE_MODE_WAKE && s_state.generation==0 &&
        s_state.begin_pending && !s_state.unbound_cancel_requested &&
        (s_state.state==WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM ||
         s_state.state==WAKE_ENGINE_STATE_ACK_PLAYING ||
         s_state.state==WAKE_ENGINE_STATE_WAIT_SPEECH ||
         s_state.state==WAKE_ENGINE_STATE_UPLOADING);
    *ticket=pending?s_state.pending_ticket:0;
    state_unlock();return pending;
}
bool wake_engine_cancel_unbound(uint64_t ticket)
{
    if(!ticket)return false;
    state_lock();
    bool requested=s_state.pending_ticket==ticket && s_state.generation==0 &&
        s_state.mode==WAKE_ENGINE_MODE_WAKE && s_state.begin_pending &&
        !s_state.unbound_cancel_requested &&
        (s_state.state==WAKE_ENGINE_STATE_WAKE_TAIL_CONFIRM ||
         s_state.state==WAKE_ENGINE_STATE_ACK_PLAYING ||
         s_state.state==WAKE_ENGINE_STATE_WAIT_SPEECH ||
         s_state.state==WAKE_ENGINE_STATE_UPLOADING);
    if(requested){s_state.unbound_cancel_requested=true;s_state.begin_pending=false;s_state.ack_pending=false;}
    state_unlock();return requested;
}

#ifdef VOICE_WAKE_DIAGNOSTICS
bool wake_engine_diag_snapshot(wake_engine_diag_t *out)
{
    if(out==NULL)return false;
    memset(out,0,sizeof(*out));
    out->available=wake_engine_available()?1U:0U;
    out->frames=__atomic_load_n(&s_diag_frames,__ATOMIC_RELAXED);
    out->detect_calls=__atomic_load_n(&s_diag_detect_calls,__ATOMIC_RELAXED);
    out->model_hits=__atomic_load_n(&s_diag_model_hits,__ATOMIC_RELAXED);
#ifndef WAKE_ENGINE_HOST_TEST
    if(s_state_lock==NULL || xSemaphoreTake(s_state_lock,0)!=pdTRUE)return false;
#endif
    out->state=s_state.state;out->mode=s_state.mode;out->generation=s_state.generation;
    out->pending=s_state.begin_pending;out->ack_pending=s_state.ack_pending;
    out->cancelled=s_state.cancel_round;out->sample_low=(uint32_t)s_sample_index;out->valid=1U;
#ifndef WAKE_ENGINE_HOST_TEST
    xSemaphoreGive(s_state_lock);
#endif
    return true;
}
#endif
