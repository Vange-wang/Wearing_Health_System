#pragma once
#include <stddef.h>
typedef enum { HEALTH_JSON_INVALID=-1,HEALTH_JSON_NOT_READY=0,HEALTH_JSON_READY=1 } health_json_result_t;
/* Input includes an owned trailing NUL at body[length]. */
health_json_result_t health_json_status(const char *body,size_t length);
