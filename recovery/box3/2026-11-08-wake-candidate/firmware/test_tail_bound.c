#include "wake_engine.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static bool detector(const int16_t *pcm, size_t n, void *context) {
    (void)pcm; (void)n; return *(bool*)context;
}
static unsigned run(bool hit, bool quiet, unsigned frames) {
    int16_t pcm[160];
    for(unsigned i=0;i<160;i++)pcm[i]=quiet?0:6000;
    assert(wake_engine_init_for_test(detector,&hit));
    wake_engine_process_frame(pcm,160);
    if(hit)assert(wake_engine_bind_capture(1));
    for(unsigned n=0;n<frames;n++)wake_engine_process_frame(pcm,160);
    unsigned events=wake_engine_take_events();wake_engine_deinit();return events;
}
int main(int argc,char **argv){
    assert(argc==2);
    assert(!(run(false,false,31)&WAKE_ENGINE_EVENT_TRIGGERED));
    assert(!(run(true,true,7)&WAKE_ENGINE_EVENT_TRIGGERED));
    assert(run(true,true,8)&WAKE_ENGINE_EVENT_TRIGGERED);
    assert(!(run(true,false,29)&WAKE_ENGINE_EVENT_TRIGGERED));
    unsigned flags=run(true,false,30);
    assert(flags & (atoi(argv[1])?WAKE_ENGINE_EVENT_TRIGGERED:WAKE_ENGINE_EVENT_CANDIDATE_REJECTED));
    puts("quiet 7/8, noisy 29/30, no model hit: PASS");
}
