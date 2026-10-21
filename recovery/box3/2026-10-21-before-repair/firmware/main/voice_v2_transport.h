#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_http_client.h"
#include "mbedtls/sha256.h"
#include "service_origin.h"

typedef bool (*voice_v2_cancel_fn)(void *);
typedef struct {
    char session[33];
    uint32_t turn, revision, segment, sample_start;
    service_origin_snapshot_t origin;
} voice_v2_identity_t;

#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
typedef struct {
    uint32_t valid,stage,errno_valid,samples;
    int32_t rc,error_number;
    int64_t last_progress_us;
} voice_v2_failure_t;
#endif

typedef struct {
    esp_http_client_handle_t client;
    mbedtls_sha256_context sha;
    voice_v2_identity_t id;
    voice_v2_cancel_fn cancelled;
    void *user;
    uint32_t samples;
    char digest[65];
    int64_t last_progress_us;
    bool open, sha_ready;
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    voice_v2_failure_t failure;
#endif
} voice_v2_transport_t;

/* Call registration only from background preparation, never a wake path. */
bool voice_v2_register_session(const service_origin_snapshot_t *,char session[33]);
bool voice_v2_open(voice_v2_transport_t *,const voice_v2_identity_t *,voice_v2_cancel_fn,void *,const char *prior_events);
bool voice_v2_write_pcm(voice_v2_transport_t *,const int16_t *,size_t samples);
bool voice_v2_end_input(voice_v2_transport_t *,bool segment_limit);
bool voice_v2_commit_boundary(voice_v2_transport_t *);
int voice_v2_fetch_status(voice_v2_transport_t *);
bool voice_v2_read_exact(voice_v2_transport_t *,void *,size_t);
bool voice_v2_event(const voice_v2_identity_t *,const char *json,size_t length);
void voice_v2_close(voice_v2_transport_t *);
