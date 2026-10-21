#pragma once
#include <stdint.h>
#include <stdbool.h>
void caption_ui_init(void); /* display initialized, caller owns LVGL lock */
void caption_ui_task(void *unused);
void caption_ui_begin(uint32_t generation);
void caption_ui_cancel(uint32_t generation);
/* Takes ownership in all cases. Never waits for display lock. */
bool caption_ui_submit(char *text, uint32_t generation);
