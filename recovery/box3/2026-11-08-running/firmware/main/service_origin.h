#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint8_t ipv4[4],instance[16];
    uint16_t port;
    uint32_t wifi_generation;
    uint64_t epoch;
    int64_t expires_us;
} service_origin_snapshot_t;
typedef enum { ORIGIN_V1_STREAM,ORIGIN_HEALTH,ORIGIN_ALERT,ORIGIN_DATA,
    ORIGIN_SESSION,ORIGIN_V2_STREAM,ORIGIN_COMMIT,ORIGIN_EVENTS } service_route_t;
typedef enum { ORIGIN_NO_CANDIDATE,ORIGIN_WAIT_IDLE,ORIGIN_CANCEL_OLD,
    ORIGIN_CAN_PUBLISH,ORIGIN_RENEWED } service_origin_action_t;

/* Network events invalidate immediately; no I/O or audio/LVGL locks. */
void service_origin_network(uint32_t generation,bool up);
bool service_origin_begin(const uint8_t nonce[16],uint32_t generation,int64_t now_us);
bool service_origin_pending(uint8_t nonce[16],uint32_t *generation,int64_t now_us);
bool service_origin_reserve(const uint8_t nonce[16],uint32_t generation,
    const uint8_t ipv4[4],const uint8_t instance[16],uint16_t ttl,int64_t now_us);
void service_origin_expire_transaction(int64_t now_us);
/* Called only by the existing session coordinator. Recheck at publish. */
service_origin_action_t service_origin_candidate(bool safe_idle,int64_t now_us);
bool service_origin_publish(bool cleanup_confirmed,int64_t now_us,service_origin_snapshot_t *out);
bool service_origin_acquire(service_origin_snapshot_t *out,bool require_ready);
bool service_origin_current(const service_origin_snapshot_t *borrowed);
bool service_origin_can_request(const service_origin_snapshot_t *borrowed);
void service_origin_health(const service_origin_snapshot_t *origin,bool ready);
void service_origin_session(const service_origin_snapshot_t *origin,bool registered);
bool service_origin_session_valid(const service_origin_snapshot_t *origin);
bool service_origin_ready(void);
bool service_origin_url(const service_origin_snapshot_t *,service_route_t,char *,size_t);
bool service_origin_headers(void *http_client,const service_origin_snapshot_t *);
#ifdef DEVICE_AUTH_DISCOVERY_SELF_TEST
bool discovery_origin_selftest(void);
#endif
