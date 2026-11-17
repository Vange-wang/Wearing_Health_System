#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
/* Returns actual drawable advance; zero selects the visible '?' fallback. */
typedef unsigned (*caption_glyph_width_t)(uint32_t cp, void *context);
typedef struct {
    size_t consumed;
    unsigned latin_words, cjk_chars;
    bool ready, continuation;
} caption_line_t;
bool caption_text_valid(const char *text, size_t length);
/* WAIT can contain a provisional complete-word prefix, with consumed == 0. */
bool caption_text_line(const char *text, size_t length, bool finished,
                       unsigned pixels, caption_glyph_width_t width, void *context,
                       char *out, size_t capacity, caption_line_t *line);
