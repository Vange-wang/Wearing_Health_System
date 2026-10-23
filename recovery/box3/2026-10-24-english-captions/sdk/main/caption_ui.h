#pragma once
#include <stdint.h>
#include <stdbool.h>
void caption_ui_init(void);
void caption_ui_task(void *unused);
void caption_ui_begin(uint32_t generation);
void caption_ui_cancel(uint32_t generation);
void caption_ui_finish(uint32_t generation);
/* Owns and frees text on every path; bounded copy, no UI-space wait. */
bool caption_ui_submit(char *text, uint32_t generation);
/* LVGL thread only, invoked by voice_agent's layout timer. Callback moves emoji
 * in the same display transaction. It never hides/scales the image. */
void caption_ui_apply_layout(void (*place_emoji)(bool expanded), int width, int height);
bool caption_ui_layout_expanded(void);
