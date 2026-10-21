#pragma once
#include <stdbool.h>
#include <stdint.h>
/* Runs only inside the existing Wi-Fi task. No extra task/stack. */
void service_discovery_init(void (*notify_coordinator)(void));
void service_discovery_poll(uint32_t wifi_generation,bool wifi_up);
uint32_t service_discovery_wait_ms(void);
