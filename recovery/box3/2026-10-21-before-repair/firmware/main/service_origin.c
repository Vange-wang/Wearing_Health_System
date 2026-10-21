#include "service_origin.h"
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#ifdef ORIGIN_HOST_TEST
extern int64_t origin_test_now(void);
#define NOW() origin_test_now()
#define LOCK() ((void)0)
#define UNLOCK() ((void)0)
#else
#include "esp_timer.h"
#include "esp_http_client.h"
#include "freertos/FreeRTOS.h"
static portMUX_TYPE s_origin_mux=portMUX_INITIALIZER_UNLOCKED;
#define NOW() esp_timer_get_time()
#define LOCK() portENTER_CRITICAL(&s_origin_mux)
#define UNLOCK() portEXIT_CRITICAL(&s_origin_mux)
#endif

static struct {
    uint32_t network;
    uint64_t epoch,health_epoch,session_epoch;
    bool up,valid,health,session,open,reserved,switching;
    uint8_t nonce[16];
    int64_t nonce_deadline,candidate_at;
    service_origin_snapshot_t active,candidate;
} s;
static bool same(const service_origin_snapshot_t *a,const service_origin_snapshot_t *b)
{return a->wifi_generation==b->wifi_generation && a->port==b->port &&
    !memcmp(a->ipv4,b->ipv4,4) && !memcmp(a->instance,b->instance,16);}
static bool current(const service_origin_snapshot_t *a)
{return s.up && s.valid && a->epoch && a->epoch==s.active.epoch && a->wifi_generation==s.network && same(a,&s.active);}
static bool candidate_valid(int64_t now)
{return s.reserved && s.up && s.candidate.wifi_generation==s.network &&
    now<s.nonce_deadline && now<s.candidate.expires_us;}
static void clear_pending(void) {s.open=false;s.reserved=false;memset(s.nonce,0,16);}
static void discard_pending(void)
{
    if(s.switching){s.health=false;s.session=false;}
    clear_pending();s.switching=false;
}
void service_origin_network(uint32_t generation,bool up)
{
    LOCK();
    if(generation<s.network){
        if(generation==0){s.up=false;s.valid=false;s.health=false;s.session=false;clear_pending();}
        UNLOCK();return;
    }
    if(generation!=s.network || up!=s.up) {
        s.network=generation;s.up=up;s.valid=false;s.health=false;s.session=false;s.switching=false;
        if(s.epoch<UINT64_MAX)s.epoch++;
        clear_pending();
    }
    UNLOCK();
}
bool service_origin_begin(const uint8_t nonce[16],uint32_t generation,int64_t now)
{
    if(!nonce || now<0 || now>INT64_MAX-4000000)return false;
    LOCK();bool ok=s.up && generation==s.network && !s.open && !s.reserved;
    if(ok){memcpy(s.nonce,nonce,16);s.nonce_deadline=now+4000000;s.open=true;}
    UNLOCK();return ok;
}
bool service_origin_pending(uint8_t nonce[16],uint32_t *generation,int64_t now)
{
    LOCK();bool ok=s.up && s.open && !s.reserved && now<s.nonce_deadline;
    if(ok){memcpy(nonce,s.nonce,16);*generation=s.network;}
    UNLOCK();return ok;
}
bool service_origin_reserve(const uint8_t nonce[16],uint32_t generation,const uint8_t ip[4],const uint8_t instance[16],uint16_t ttl,int64_t now)
{
    if(!nonce || !ip || !instance || ttl<30 || ttl>120 || now<0 || now>INT64_MAX-120000000)return false;
    LOCK();bool ok=s.up && s.open && !s.reserved && generation==s.network && now<s.nonce_deadline && !memcmp(nonce,s.nonce,16);
    if(ok){
        memset(&s.candidate,0,sizeof(s.candidate));memcpy(s.candidate.ipv4,ip,4);memcpy(s.candidate.instance,instance,16);
        s.candidate.port=8710;s.candidate.wifi_generation=generation;s.candidate.expires_us=now+(int64_t)ttl*1000000;
        s.candidate_at=now;s.reserved=true;s.open=false;
        s.switching=!s.valid || !same(&s.active,&s.candidate);
    }
    UNLOCK();return ok;
}
void service_origin_expire_transaction(int64_t now)
{
    LOCK();if((s.open || s.reserved) && now>=s.nonce_deadline){
        discard_pending();
    }UNLOCK();
}
service_origin_action_t service_origin_candidate(bool safe_idle,int64_t now)
{
    LOCK();service_origin_action_t action=ORIGIN_NO_CANDIDATE;
    if(candidate_valid(now)) {
        if(s.valid && same(&s.active,&s.candidate)) {
            s.active.expires_us=s.candidate.expires_us;clear_pending();s.switching=false;action=ORIGIN_RENEWED;
        } else if(safe_idle)action=ORIGIN_CAN_PUBLISH;
        else action=now-s.candidate_at>=1000000?ORIGIN_CANCEL_OLD:ORIGIN_WAIT_IDLE;
    } else if(s.reserved) {discard_pending();}
    UNLOCK();return action;
}
bool service_origin_publish(bool cleanup_confirmed,int64_t now,service_origin_snapshot_t *out)
{
    LOCK();bool ok=cleanup_confirmed && out && candidate_valid(now) && s.epoch<UINT64_MAX;
    if(ok){
        s.health=false;s.session=false;s.active=s.candidate;s.active.epoch=++s.epoch;
        s.valid=true;s.switching=false;clear_pending();*out=s.active;
    }UNLOCK();return ok;
}
bool service_origin_acquire(service_origin_snapshot_t *out,bool require_ready)
{
    int64_t now=NOW();LOCK();
    bool ok=out && s.up && s.valid && !s.switching && now<s.active.expires_us;
    if(require_ready)ok=ok && s.health && s.session && s.health_epoch==s.active.epoch && s.session_epoch==s.active.epoch;
    if(ok){*out=s.active;}
    UNLOCK();return ok;
}
bool service_origin_current(const service_origin_snapshot_t *borrowed)
{if(!borrowed)return false;LOCK();bool ok=current(borrowed);UNLOCK();return ok;}
bool service_origin_can_request(const service_origin_snapshot_t *borrowed)
{if(!borrowed)return false;LOCK();bool ok=current(borrowed) && !s.switching && NOW()<s.active.expires_us;UNLOCK();return ok;}
void service_origin_health(const service_origin_snapshot_t *origin,bool ready)
{LOCK();if(origin && current(origin) && !s.switching && NOW()<s.active.expires_us){s.health=ready;s.health_epoch=origin->epoch;}UNLOCK();}
void service_origin_session(const service_origin_snapshot_t *origin,bool registered)
{LOCK();if(origin && current(origin) && !s.switching && NOW()<s.active.expires_us){s.session=registered;s.session_epoch=origin->epoch;}UNLOCK();}
bool service_origin_session_valid(const service_origin_snapshot_t *origin)
{LOCK();bool ok=origin && current(origin) && s.session && s.session_epoch==origin->epoch;UNLOCK();return ok;}
bool service_origin_ready(void){service_origin_snapshot_t borrowed;return service_origin_acquire(&borrowed,true);}
bool service_origin_url(const service_origin_snapshot_t *o,service_route_t route,char *out,size_t size)
{
    static const char *const paths[]={"/api/v1/voice/stream","/api/v2/voice/health","/api/v1/health/alert","/api/v1/health/data",
        "/api/v2/voice/session","/api/v2/voice/stream","/api/v2/voice/commit","/api/v2/voice/events"};
    if(!o || !out || !o->epoch || o->port!=8710 || (unsigned)route>=sizeof(paths)/sizeof(paths[0]))return false;
    int n=snprintf(out,size,"http://%u.%u.%u.%u:8710%s",o->ipv4[0],o->ipv4[1],o->ipv4[2],o->ipv4[3],paths[route]);
    return n>0 && (size_t)n<size;
}
bool service_origin_headers(void *http,const service_origin_snapshot_t *origin)
{
#ifdef ORIGIN_HOST_TEST
    (void)http;(void)origin;return false;
#else
    if(!http || !origin || !origin->epoch)return false;
    char instance[33],epoch[21];static const char hex[]="0123456789abcdef";
    for(unsigned i=0;i<16;i++){instance[2*i]=hex[origin->instance[i]>>4];instance[2*i+1]=hex[origin->instance[i]&15];}instance[32]=0;
    snprintf(epoch,sizeof(epoch),"%" PRIu64,origin->epoch);
    return esp_http_client_set_header(http,"X-Voice-Client","box3")==0 &&
        esp_http_client_set_header(http,"X-Voice-PC-Instance",instance)==0 &&
        esp_http_client_set_header(http,"X-Voice-Origin-Epoch",epoch)==0;
#endif
}
