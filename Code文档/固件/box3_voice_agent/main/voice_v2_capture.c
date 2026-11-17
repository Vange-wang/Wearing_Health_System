#include "voice_v2_capture.h"
#include <string.h>

static bool fail(v2_capture_t *s){s->failed=true;return false;}
static bool start(v2_capture_t *s)
{
    if(s->failed || s->next_seq>=V2_CAPTURE_MAX_SEGMENTS)return fail(s);
    for(unsigned i=0;i<V2_CAPTURE_SLOTS;i++)if(s->slots[i].state==V2_SLOT_FREE){
        v2_capture_slot_t *slot=&s->slots[i];
        slot->written=slot->read=0;slot->seq=s->next_seq++;slot->start=s->next_start;
        slot->state=V2_SLOT_WRITING;slot->segment_limit=false;slot->leased=false;
        s->filling=(int)i;s->revision=slot->seq+1;return true;
    }
    return fail(s);
}
void v2_capture_init(v2_capture_t *s,int16_t *a,int16_t *b)
{memset(s,0,sizeof(*s));s->slots[0].pcm=a;s->slots[1].pcm=b;s->filling=-1;}
void v2_capture_reset(v2_capture_t *s,uint32_t generation)
{
    int16_t *a=s->slots[0].pcm,*b=s->slots[1].pcm;
    /* Called only after network owner releases its lease; erase prior audio. */
    for(unsigned i=0;i<V2_CAPTURE_SLOTS;i++) {
        v2_capture_slot_t *slot=&s->slots[i];
        if(slot->pcm && slot->written>slot->read)
            memset(slot->pcm+slot->read,0,(slot->written-slot->read)*sizeof(*slot->pcm));
    }
    v2_capture_init(s,a,b);s->generation=generation;
    if(!generation || !a || !b){s->failed=true;return;}
    start(s);
}
bool v2_capture_append(v2_capture_t *s,const int16_t *pcm,size_t count)
{
    if(s->failed || s->playing || s->waiting || (!pcm && count))return false;
    if(count>V2_CAPTURE_MAX_SAMPLES-s->next_start)return fail(s);
    while(count){
        if(s->filling<0 && !start(s))return false;
        v2_capture_slot_t *slot=&s->slots[s->filling];
        size_t n=V2_CAPTURE_SEGMENT_SAMPLES-slot->written;if(n>count)n=count;
        memcpy(slot->pcm+slot->written,pcm,n*sizeof(*pcm));
        slot->written+=n;s->next_start+=(uint32_t)n;pcm+=n;count-=n;
        if(slot->written==V2_CAPTURE_SEGMENT_SAMPLES){
            slot->state=V2_SLOT_SEALED;slot->segment_limit=true;s->filling=-1;
        }
    }
    return true;
}
bool v2_capture_endpoint(v2_capture_t *s)
{
    if(s->failed || s->playing || s->waiting)return false;
    if(s->filling>=0){
        v2_capture_slot_t *slot=&s->slots[s->filling];
        if(!slot->written)return fail(s);
        slot->state=V2_SLOT_SEALED;slot->segment_limit=false;s->filling=-1;
    }else{
        /* Exactly on a segment boundary: commit the existing segment, never
         * fabricate a zero-only ASR segment. Network owner sends commit. */
        s->commit_pending=true;
    }
    s->waiting=true;return true;
}
bool v2_capture_continue(v2_capture_t *s)
{
    if(s->failed || s->playing || !s->waiting)return false;
    if(s->committing){s->continuation_pending=true;return false;}
    s->waiting=false;s->commit_pending=false;
    return start(s);
}
bool v2_capture_pcm_begin(v2_capture_t *s,uint32_t revision)
{
    if(s->failed || !s->waiting || s->playing || s->committing || s->revision!=revision)return false;
    s->committing=true;return true;
}
bool v2_capture_pcm_complete(v2_capture_t *s,uint32_t revision,bool success)
{
    if(!s->committing || s->revision!=revision)return false;
    s->committing=false;
    if(!success || s->failed)return fail(s);
    s->playing=true;return true;
}
bool v2_capture_mark_playing(v2_capture_t *s,uint32_t revision)
{
    if(s->failed || s->committing || !s->waiting || s->revision!=revision)return false;
    s->playing=true;return true;
}
int v2_capture_acquire(v2_capture_t *s)
{
    if(s->failed)return -1;
    int found=-1;
    for(unsigned i=0;i<V2_CAPTURE_SLOTS;i++){
        v2_capture_slot_t *slot=&s->slots[i];
        if(slot->state==V2_SLOT_FREE || slot->leased)continue;
        if(found<0 || slot->seq<s->slots[found].seq)found=(int)i;
    }
    if(found>=0)s->slots[found].leased=true;
    return found;
}
size_t v2_capture_read(v2_capture_t *s,int index,int16_t *out,size_t capacity)
{
    if(s->failed || index<0 || index>=(int)V2_CAPTURE_SLOTS || !out)return 0;
    v2_capture_slot_t *slot=&s->slots[index];if(!slot->leased)return 0;
    size_t n=slot->written-slot->read;if(n>capacity)n=capacity;
    memcpy(out,slot->pcm+slot->read,n*sizeof(*out));
    memset(slot->pcm+slot->read,0,n*sizeof(*out));slot->read+=n;return n;
}
bool v2_capture_release(v2_capture_t *s,int index)
{
    if(index<0 || index>=(int)V2_CAPTURE_SLOTS)return false;
    v2_capture_slot_t *slot=&s->slots[index];
    if(!slot->leased || slot->state!=V2_SLOT_SEALED || slot->read!=slot->written)return false;
    slot->state=V2_SLOT_FREE;slot->leased=false;slot->written=slot->read=0;return true;
}
