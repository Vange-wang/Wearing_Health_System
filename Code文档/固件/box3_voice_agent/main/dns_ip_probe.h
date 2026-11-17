#pragma once
#include <stdint.h>
void dns_ip_probe_request(uint32_t generation);
void dns_ip_probe_poll(uint32_t (*current_generation)(void));
