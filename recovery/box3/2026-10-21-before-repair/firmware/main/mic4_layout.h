#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct { uint8_t mic1,mic2,reference,unused; bool verified; } mic4_layout_t;
typedef struct {
    uint64_t samples,energy[4];
    uint32_t clipped[4];
    uint16_t peak[4];
} mic4_stats_t;
/* Indices identify the four little-endian halfwords in each 8-byte RX record.
 * No default mapping: source-code packing is not a physical channel test. */
bool mic4_layout_valid(const mic4_layout_t *);
bool mic4_unpack(const uint8_t *raw,size_t length,const mic4_layout_t *,
                 int16_t *mic_ref_pairs,size_t frame_capacity);
bool mic4_measure(const uint8_t *raw,size_t length,mic4_stats_t *);
