#pragma once
#include <stdbool.h>
#include <stddef.h>
bool caption_text_valid(const char *text,size_t length);
bool caption_text_page(const char *text,size_t length,size_t *offset,char *out,size_t capacity);
