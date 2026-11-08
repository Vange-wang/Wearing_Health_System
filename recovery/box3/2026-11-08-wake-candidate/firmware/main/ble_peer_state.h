#pragma once
#include "ble_central.h"
#include "health_source.h"
#include <stddef.h>
enum { BP_FREE=0,BP_CONNECTING=1,BP_DISCOVERING=2,BP_READY=3,BP_CLOSING=4 };
#define BP_COUNT 2U
#define BP_FRESH_US 60000000ULL
typedef struct {
 uint8_t address_type,address[6],phase;
 uint16_t handle;
 uint32_t token;
 health_source_t source;
 ble_health_t latest,good;
 uint64_t good_us;
 bool have_good;
} ble_peer_t;
typedef struct {
 ble_peer_t peer[BP_COUNT];
 uint32_t next_token;
 uint64_t output_epoch;
 int selected;
 uint32_t selected_token;
 ble_health_t output;
 bool output_valid,handover_pending;
} ble_peer_bank_t;
void bp_init(ble_peer_bank_t *b);
int bp_find(ble_peer_bank_t *b,uint32_t token,uint16_t handle);
int bp_reserve(ble_peer_bank_t *b,uint8_t type,const uint8_t address[6]);
bool bp_connected(ble_peer_bank_t *b,uint32_t token,uint16_t handle);
bool bp_ready(ble_peer_bank_t *b,uint32_t token,uint16_t handle);
void bp_drop(ble_peer_bank_t *b,uint32_t token,uint64_t now);
health_source_result_t bp_frame(ble_peer_bank_t *b,uint32_t token,uint16_t handle,const uint8_t f[8],uint64_t now);
void bp_select(ble_peer_bank_t *b,uint64_t now);
bool bp_current(ble_peer_bank_t *b,const ble_health_t *h);
void bp_uploaded(ble_peer_bank_t *b,const ble_health_t *h);
void bp_snapshot(ble_peer_bank_t *b,unsigned slot,ble_node_snapshot_t *out);
