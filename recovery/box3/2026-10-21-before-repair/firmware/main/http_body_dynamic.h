#pragma once

#include <stddef.h>
#include <stdint.h>
#include "esp_http_client.h"

typedef enum {
    HTTP_BODY_OK = 0,
    HTTP_BODY_ARGUMENT,
    HTTP_BODY_IO,
    HTTP_BODY_INCOMPLETE,
    HTTP_BODY_NO_MEMORY,
    HTTP_BODY_SIZE_OVERFLOW,
    HTTP_BODY_LENGTH_MISMATCH,
} http_body_result_t;

/* After response headers have been fetched. No content-size policy cap.
 * On success caller owns *body and must free it. Failure returns no buffer.
 * Transport timeout is the client's existing timeout; never retry/reconnect.
 */
http_body_result_t http_body_read_dynamic(esp_http_client_handle_t client,
                                         char **body, size_t *length);
const char *http_body_result_name(http_body_result_t result);
bool http_body_size_fits(uint64_t used,uint64_t incoming,uint64_t platform_size_max);
