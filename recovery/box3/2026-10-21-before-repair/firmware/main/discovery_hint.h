#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "service_origin.h"

/* Boot-only NVS read, before interactive voice tasks. Never loads credentials. */
void discovery_hint_init(void);
/* RAM only. WiFi task owns network metadata; no NVS in discovery polling. */
void discovery_hint_network(uint32_t generation,bool up,const uint8_t local[4],const uint8_t mask[4]);
/* Returns 0 (broadcast) or 2 (untrusted cache). */
unsigned discovery_hint_target(const uint8_t local[4],const uint8_t mask[4],uint8_t target[4]);
/* Revalidates complete current READY; copies only a bounded RAM candidate. */
void discovery_hint_note_ready(const service_origin_snapshot_t *origin);
