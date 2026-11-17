#include "public_pcm_feed.h"
#ifdef VOICE_PUBLIC_PCM_INJECTION
#ifdef WAKE_ENGINE_HOST_TEST
#error Public REAL_MODEL injection must not replace the actual detector.
#endif
#include <limits.h>
#include <string.h>
#include "public_pcm_data.inc"
_Static_assert(sizeof(public_keyword_pcm)+sizeof(public_question_pcm)==102400U,"Public input must be exactly100KiB");
typedef struct {
    uint32_t phase,error,rounds_started,rounds_completed,records,keyword_samples,question_samples;
    uint32_t deadline_ms,talk_done;
    uint32_t first_pcm,valid_D,tx_receipt,receive_ok,receive_failed,round_flags[3];
} public_visible_t;
static public_visible_t v;
static struct {
    int64_t started_us,last_us,deadline_us,keyword_done_us;
    size_t cursor,warm_left;
    uint32_t hit_base,ack_base,turn_base,done_base;
    uint32_t first_base,D_base,tx_base,ok_base,failed_base;
} s;
#define GET(x) __atomic_load_n(&v.x,__ATOMIC_RELAXED)
#define SET(x,n) __atomic_store_n(&v.x,(uint32_t)(n),__ATOMIC_RELAXED)
#define ADD(x,n) ((void)__atomic_fetch_add(&v.x,(uint32_t)(n),__ATOMIC_RELAXED))
static void fail(uint32_t code) {SET(error,code);SET(phase,PUBLIC_PCM_FAILED);}
static void phase(uint32_t next,int64_t now,int64_t budget)
{
    s.deadline_us=now+budget;SET(deadline_ms,(uint32_t)(s.deadline_us/1000));SET(phase,next);
}
void public_pcm_start(int64_t now)
{
    memset(&s,0,sizeof(s));memset(&v,0,sizeof(v));
    s.started_us=s.last_us=now;
    if(now<0 || now>INT64_MAX-300000000LL){fail(PUBLIC_PCM_CLOCK);return;}
    phase(PUBLIC_PCM_WAIT_ARM,now,120000000LL);
}
void public_pcm_talk_done(void) {ADD(talk_done,1);}
void public_pcm_response_event(uint32_t kind)
{
    if(kind==1U)ADD(first_pcm,1);
    else if(kind==2U)ADD(valid_D,1);
    else if(kind==3U)ADD(tx_receipt,1);
    else if(kind==4U)ADD(receive_ok,1);
    else if(kind==5U)ADD(receive_failed,1);
}
uint32_t public_pcm_talk_done_count(void) {return GET(talk_done);}
void public_pcm_read_fault(void) {if(GET(phase)!=PUBLIC_PCM_DONE)fail(PUBLIC_PCM_READ_FAULT);}
static bool gate(const public_pcm_input_t *in)
{return in->valid && in->available && in->origin_ready && in->output_idle && in->state==3U && in->mode==1U;}
static void begin_question(const public_pcm_input_t *in)
{
    s.cursor=0;s.turn_base=in->turn_begin;s.done_base=in->talk_done;
    s.first_base=GET(first_pcm);s.D_base=GET(valid_D);s.tx_base=GET(tx_receipt);
    s.ok_base=GET(receive_ok);s.failed_base=GET(receive_failed);
    ADD(rounds_started,1);phase(PUBLIC_PCM_QUESTION,in->now_us,5000000LL);
}
static void put_pcm(uint8_t *raw,size_t frames,const int16_t *pcm,size_t count,bool keyword)
{
    size_t take=count-s.cursor;if(take>frames)take=frames;
    for(size_t i=0;i<take;i++) {
        uint16_t bits=(uint16_t)pcm[s.cursor+i];
        raw[8*i+2]=(uint8_t)bits;raw[8*i+3]=(uint8_t)(bits>>8);
        raw[8*i+6]=(uint8_t)bits;raw[8*i+7]=(uint8_t)(bits>>8);
    }
    s.cursor+=take;if(keyword)ADD(keyword_samples,take);else ADD(question_samples,take);
}
bool public_pcm_record(uint8_t *raw,size_t bytes,size_t capacity,const public_pcm_input_t *in)
{
    if(!raw || bytes>capacity){fail(PUBLIC_PCM_FORMAT);return false;}
    memset(raw,0,bytes); /* No phase ever returns a hardware/private passthrough. */
    if(!in || !bytes || bytes%8U){fail(PUBLIC_PCM_FORMAT);return false;}
    ADD(records,1);
    if(GET(phase)==PUBLIC_PCM_DONE || GET(phase)==PUBLIC_PCM_FAILED)return true;
    int64_t now=in->now_us;
    if(now<0 || now<s.last_us || now>INT64_MAX-300000000LL){fail(PUBLIC_PCM_CLOCK);return true;}
    s.last_us=now;
    if(now-s.started_us>=300000000LL){fail(PUBLIC_PCM_CASE_TIMEOUT);return true;}
    uint32_t p=GET(phase);
    if(p!=PUBLIC_PCM_WAIT_ARM && in->valid && in->mode==2U){fail(PUBLIC_PCM_KEY_TAKEOVER);return true;}
    if(p==PUBLIC_PCM_WAIT_ARM) {
        if(now>=s.deadline_us){fail(PUBLIC_PCM_ARM_TIMEOUT);return true;}
        if(in->valid && in->available && in->origin_ready && in->capture_idle && in->output_idle && in->state==0U && in->mode==0U) {
            s.hit_base=in->model_hits;s.ack_base=in->ack_done;s.turn_base=in->turn_begin;s.done_base=in->talk_done;
            s.warm_left=8000;phase(PUBLIC_PCM_WARM,now,2000000LL);
        }
        return true;
    }
    if(p==PUBLIC_PCM_WAIT_FIRST) {
        if(in->turn_begin!=s.turn_base || in->talk_done!=s.done_base){fail(PUBLIC_PCM_UNEXPECTED_TURN);return true;}
        if(in->valid && now-s.keyword_done_us>=3000000LL && in->model_hits==s.hit_base){fail(PUBLIC_PCM_MODEL_MISS);return true;}
        if(now>=s.deadline_us){fail(PUBLIC_PCM_GATE_TIMEOUT);return true;}
        if(gate(in) && in->generation!=0 && in->model_hits!=s.hit_base && in->ack_done!=s.ack_base)begin_question(in);
        return true;
    }
    if(p==PUBLIC_PCM_WAIT_ROUND) {
        if(now>=s.deadline_us){fail(PUBLIC_PCM_ROUND_TIMEOUT);return true;}
        if(gate(in) && in->capture_idle && in->generation==0 && in->talk_done!=s.done_base && in->turn_begin!=s.turn_base) {
            uint32_t flags=(GET(first_pcm)!=s.first_base?1U:0U)|(GET(valid_D)!=s.D_base?2U:0U)|
                (GET(tx_receipt)!=s.tx_base?4U:0U)|(GET(receive_ok)!=s.ok_base?8U:0U)|
                (GET(receive_failed)!=s.failed_base?16U:0U);
            uint32_t index=GET(rounds_started)-1U;
            if(index<3U)__atomic_store_n(&v.round_flags[index],flags,__ATOMIC_RELAXED);
            ADD(rounds_completed,1);
            if(GET(rounds_completed)==3U)phase(PUBLIC_PCM_DONE,now,0);
            else begin_question(in);
        }
        return true;
    }
    if(now>=s.deadline_us){fail(PUBLIC_PCM_SOURCE_TIMEOUT);return true;}
    if(!in->origin_ready){fail(PUBLIC_PCM_ORIGIN_LOST);return true;}
    size_t frames=bytes/8U;
    if(p==PUBLIC_PCM_WARM) {
        if(in->valid && in->model_hits!=s.hit_base){fail(PUBLIC_PCM_EARLY_MODEL_HIT);return true;}
        if(frames>=s.warm_left){s.cursor=0;phase(PUBLIC_PCM_KEYWORD,now,5000000LL);}
        else s.warm_left-=frames;
        return true;
    }
    if(p==PUBLIC_PCM_KEYWORD) {
        put_pcm(raw,frames,public_keyword_pcm,20480U,true);
        if(s.cursor==20480U){s.keyword_done_us=now;phase(PUBLIC_PCM_WAIT_FIRST,now,10000000LL);}
        return true;
    }
    if(p==PUBLIC_PCM_QUESTION) {
        if(in->talk_done!=s.done_base){fail(PUBLIC_PCM_EARLY_TALK_END);return true;}
        put_pcm(raw,frames,public_question_pcm,30720U,false);
        if(s.cursor==30720U)phase(PUBLIC_PCM_WAIT_ROUND,now,60000000LL);
        return true;
    }
    fail(PUBLIC_PCM_FORMAT);return true;
}
void public_pcm_diagnostic(int64_t now,public_pcm_diag_t *out)
{
    if(!out)return;
    *out=(public_pcm_diag_t){.phase=GET(phase),.error=GET(error),.rounds_started=GET(rounds_started),
        .rounds_completed=GET(rounds_completed),.records=GET(records),.keyword_samples=GET(keyword_samples),
        .question_samples=GET(question_samples),.talk_done=GET(talk_done),.fixture_id=2026101801U,
        .keyword_hash32=0x4389516dU,.question_hash32=0x754ffad7U};
    out->first_pcm=GET(first_pcm);out->valid_D=GET(valid_D);out->tx_receipt=GET(tx_receipt);
    out->receive_ok=GET(receive_ok);out->receive_failed=GET(receive_failed);
    for(unsigned i=0;i<3U;i++)out->round_flags[i]=__atomic_load_n(&v.round_flags[i],__ATOMIC_RELAXED);
    /* DONE means three driven attempts. Only the external real PC/device gate can pass end-to-end. */
    out->outcome=out->phase==PUBLIC_PCM_DONE?1U:out->phase==PUBLIC_PCM_FAILED?2U:0U;
    if(now>=0 && out->phase!=PUBLIC_PCM_DONE && out->phase!=PUBLIC_PCM_FAILED)
        out->deadline_expired=(int32_t)((uint32_t)(now/1000)-GET(deadline_ms))>=0?1U:0U;
}
#endif
