#pragma once
/* Diagnostic build only. Numeric counters, never PCM storage or hot-path I/O. */
#ifdef VOICE_WAKE_DIAGNOSTICS
#include <stdint.h>
#include <stddef.h>
typedef struct {
    uint32_t read_begin,read_ok,read_error,read_return,read_tick,frame_tick,read_phase,read_rc;
    uint32_t talk_loops,talk_phase,origin_reject,ack_pcm,ack_done,turn_begin,recovery;
    uint32_t slot0,slot1,slot2,slot3;
} voice_wake_diag_t;
static voice_wake_diag_t s_voice_diag;
#define VD_INC(x) ((void)__atomic_fetch_add(&s_voice_diag.x,1U,__ATOMIC_RELAXED))
#define VD_SET(x,v) __atomic_store_n(&s_voice_diag.x,(uint32_t)(v),__ATOMIC_RELAXED)
#define VD_GET(x) __atomic_load_n(&s_voice_diag.x,__ATOMIC_RELAXED)
static void voice_diag_slots(const void *data,size_t bytes)
{
    const uint8_t *p=(const uint8_t *)data;uint32_t peaks[4]={0};
    if(data==NULL || bytes%8U)return;
    for(size_t i=0;i<bytes;i+=8U)for(unsigned j=0;j<4U;j++) {
        unsigned at=(unsigned)(i+2U*j);
        int32_t n=(int32_t)((uint16_t)p[at]|((uint16_t)p[at+1U]<<8));
        if(n>=32768)n-=65536;
        uint32_t magnitude=(uint32_t)(n<0?-n:n);
        if(magnitude>peaks[j])peaks[j]=magnitude;
    }
    VD_SET(slot0,peaks[0]);VD_SET(slot1,peaks[1]);VD_SET(slot2,peaks[2]);VD_SET(slot3,peaks[3]);
}
#else
#define VD_INC(x) ((void)0)
#define VD_SET(x,v) ((void)0)
#define voice_diag_slots(p,n) ((void)0)
#endif
