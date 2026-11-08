#pragma once
#include <stdbool.h>
#include <stdint.h>
bool display_dispatch_init(bool (*emoji)(const char *), bool (*visual)(uint32_t));
void display_dispatch_emoji(const char *static_path);
void display_dispatch_visual(uint32_t command);
void display_dispatch_heartbeat(void *unused);
