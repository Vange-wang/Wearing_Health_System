#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define DISCOVERY_REQUEST_BYTES 58
#define DISCOVERY_RESPONSE_BYTES 82
typedef struct { uint8_t ipv4[4],instance[16];uint16_t ttl; } paired_discovery_reply_t;
bool paired_discovery_request(const uint8_t nonce[16],uint8_t out[58]);
bool paired_discovery_response(const uint8_t *,size_t,const uint8_t source[4],uint16_t source_port,
    const uint8_t nonce[16],const uint8_t local[4],const uint8_t netmask[4],paired_discovery_reply_t *);
