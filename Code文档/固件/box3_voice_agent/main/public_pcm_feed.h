#pragma once
#ifdef VOICE_PUBLIC_PCM_INJECTION
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
enum { PUBLIC_PCM_WAIT_ARM,PUBLIC_PCM_WARM,PUBLIC_PCM_KEYWORD,
       PUBLIC_PCM_WAIT_FIRST,PUBLIC_PCM_QUESTION,PUBLIC_PCM_WAIT_ROUND,
       PUBLIC_PCM_DONE,PUBLIC_PCM_FAILED };
enum { PUBLIC_PCM_NO_ERROR,PUBLIC_PCM_READ_FAULT,PUBLIC_PCM_FORMAT,
       PUBLIC_PCM_CLOCK,PUBLIC_PCM_ARM_TIMEOUT,PUBLIC_PCM_MODEL_MISS,
       PUBLIC_PCM_GATE_TIMEOUT,PUBLIC_PCM_ROUND_TIMEOUT,PUBLIC_PCM_CASE_TIMEOUT,
       PUBLIC_PCM_EARLY_TALK_END,PUBLIC_PCM_UNEXPECTED_TURN,PUBLIC_PCM_KEY_TAKEOVER,
       PUBLIC_PCM_ORIGIN_LOST,PUBLIC_PCM_SOURCE_TIMEOUT,PUBLIC_PCM_EARLY_MODEL_HIT };
typedef struct {
    int64_t now_us;
    uint32_t valid,available,state,mode,generation,origin_ready,capture_idle,output_idle;
    uint32_t model_hits,ack_done,turn_begin,talk_done;
} public_pcm_input_t;
typedef struct {
    uint32_t phase,error,rounds_started,rounds_completed,records,keyword_samples,question_samples;
    uint32_t deadline_expired,talk_done,fixture_id,keyword_hash32,question_hash32;
    uint32_t first_pcm,valid_D,tx_receipt,receive_ok,receive_failed,round_flags[3],outcome;
} public_pcm_diag_t;
void public_pcm_start(int64_t now_us);
bool public_pcm_record(uint8_t *raw,size_t bytes,size_t capacity,const public_pcm_input_t *input);
void public_pcm_read_fault(void);
void public_pcm_talk_done(void);
void public_pcm_response_event(uint32_t kind);
uint32_t public_pcm_talk_done_count(void);
void public_pcm_diagnostic(int64_t now_us,public_pcm_diag_t *out);
#endif
