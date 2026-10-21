/* Diagnostic-only public seam tests. Separate state, fake clock, no network/credentials. */
#define ORIGIN_HOST_TEST 1
#define origin_test_now discovery_test_now
#define service_origin_network discovery_test_network
#define service_origin_begin discovery_test_begin
#define service_origin_pending discovery_test_pending
#define service_origin_reserve discovery_test_reserve
#define service_origin_expire_transaction discovery_test_expire_transaction
#define service_origin_candidate discovery_test_candidate
#define service_origin_publish discovery_test_publish
#define service_origin_acquire discovery_test_acquire
#define service_origin_current discovery_test_current
#define service_origin_can_request discovery_test_can_request
#define service_origin_health discovery_test_health
#define service_origin_session discovery_test_session
#define service_origin_session_valid discovery_test_session_valid
#define service_origin_ready discovery_test_ready
#define service_origin_url discovery_test_url
#define service_origin_headers discovery_test_headers
#include "service_origin.c"
#define CHECK(test) do { if(!(test)) return false; } while(0)
/* Host compiler only: -DORIGIN_HOST_TEST service_origin.c origin_host_test.c */
#include "service_origin.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
static int64_t now;
int64_t origin_test_now(void){return now;}
bool discovery_origin_selftest(void)
{
    uint8_t nonce[16]={1},instance[16]={2},ip[4]={192,168,1,113};
    service_origin_snapshot_t first,renewed,next,borrowed;
    service_origin_network(1,true);
    CHECK(!service_origin_ready());
    CHECK(service_origin_begin(nonce,1,0));
    CHECK(service_origin_reserve(nonce,1,ip,instance,120,100));
    CHECK(!service_origin_reserve(nonce,1,ip,instance,120,101));
    CHECK(service_origin_candidate(true,200)==ORIGIN_CAN_PUBLISH);
    CHECK(!service_origin_publish(false,200,&first));
    CHECK(service_origin_publish(true,200,&first));
    CHECK(!service_origin_ready());
    service_origin_health(&first,true);CHECK(!service_origin_ready());
    service_origin_session(&first,true);CHECK(service_origin_acquire(&borrowed,true));
    now=1000000;nonce[0]=3;
    CHECK(service_origin_begin(nonce,1,now));
    CHECK(service_origin_reserve(nonce,1,ip,instance,120,now));
    CHECK(service_origin_candidate(false,now)==ORIGIN_RENEWED);
    CHECK(service_origin_acquire(&renewed,true) && renewed.epoch==first.epoch && renewed.expires_us>first.expires_us);
    instance[0]=4;nonce[0]=5;now=2000000;
    CHECK(service_origin_begin(nonce,1,now));CHECK(service_origin_reserve(nonce,1,ip,instance,120,now));
    CHECK(!service_origin_ready());
    CHECK(service_origin_candidate(false,now)==ORIGIN_WAIT_IDLE);
    CHECK(service_origin_candidate(false,now+1000000)==ORIGIN_CANCEL_OLD);
    CHECK(service_origin_current(&borrowed));
    CHECK(service_origin_publish(true,now+1000001,&next));
    CHECK(next.epoch>first.epoch && !service_origin_current(&borrowed));
    service_origin_health(&first,true);service_origin_session(&first,true);CHECK(!service_origin_ready());
    service_origin_health(&next,true);service_origin_session(&next,true);CHECK(service_origin_ready());
    char url[96];
    for(int route=ORIGIN_V1_STREAM;route<=ORIGIN_EVENTS;route++){
        CHECK(service_origin_url(&next,(service_route_t)route,url,sizeof(url)));
        CHECK(strncmp(url,"http://192.168.1.113:8710/",sizeof("http://192.168.1.113:8710/")-1)==0);
    }
    now=next.expires_us;
    CHECK(!service_origin_ready() && !service_origin_acquire(&renewed,false));
    CHECK(service_origin_current(&next)); /* already-started immutable request */
    CHECK(!service_origin_can_request(&next));
    service_origin_network(2,true);CHECK(!service_origin_current(&next));
    nonce[0]=6;CHECK(!service_origin_begin(nonce,1,now));
    CHECK(service_origin_begin(nonce,2,now));
    CHECK(!service_origin_reserve(nonce,1,ip,instance,120,now));
    CHECK(service_origin_reserve(nonce,2,ip,instance,120,now));
    service_origin_network(3,true);CHECK(!service_origin_publish(true,now+1,&next));
    CHECK(service_origin_begin(nonce,3,now));CHECK(service_origin_reserve(nonce,3,ip,instance,30,now));
    CHECK(!service_origin_publish(true,now+4000000,&next));
    service_origin_expire_transaction(now+4000000);
    CHECK(!service_origin_ready());return true;
}
