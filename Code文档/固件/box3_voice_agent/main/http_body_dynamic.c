#include "http_body_dynamic.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "esp_timer.h"

bool http_body_size_fits(uint64_t used,uint64_t incoming,uint64_t platform_size_max)
{
    return used<platform_size_max && incoming<=platform_size_max-used-1U;
}

http_body_result_t http_body_read_dynamic(esp_http_client_handle_t client,
                                         char **body, size_t *length)
{
    if (body == NULL || length == NULL) return HTTP_BODY_ARGUMENT;
    *body = NULL;
    *length = 0;
    if (client == NULL) return HTTP_BODY_ARGUMENT;

    const bool chunked = esp_http_client_is_chunked_response(client);
    const int64_t declared = esp_http_client_get_content_length(client);
    if (!chunked && declared >= 0 && !http_body_size_fits(0,(uint64_t)declared,SIZE_MAX))
        return HTTP_BODY_SIZE_OVERFLOW;

    char *data = NULL;
    size_t used = 0, capacity = 0;
    http_body_result_t result = HTTP_BODY_OK;
    /* Scratch size is an I/O granularity, never a response-length limit. */
    char scratch[1024];
    const int64_t deadline = esp_timer_get_time() + 2000000;
    /* The SDK's completion flag describes parser progress, not consumption of
     * cached raw_data. Always drain read(), including when headers already
     * buffered the entire body; then validate completion after a zero read. */
    while (true) {
        int64_t remaining = deadline - esp_timer_get_time();
        if (remaining <= 0) { result = HTTP_BODY_IO; goto fail; }
        esp_http_client_set_timeout_ms(client, (int)((remaining + 999) / 1000));
        int received = esp_http_client_read(client, scratch, sizeof(scratch));
        if (received < 0) { result = HTTP_BODY_IO; goto fail; }
        if (received == 0) {
            if (!esp_http_client_is_complete_data_received(client)) {
                result = HTTP_BODY_INCOMPLETE; goto fail;
            }
            break;
        }
        if ((size_t)received > sizeof(scratch) ||
            !http_body_size_fits(used,(size_t)received,SIZE_MAX)) {
            result = HTTP_BODY_SIZE_OVERFLOW; goto fail;
        }
        size_t required = used + (size_t)received + 1U;
        if (required > capacity) {
            size_t grown = capacity == 0 ? sizeof(scratch) + 1U : capacity;
            while (grown < required) {
                if (grown > SIZE_MAX / 2U) { grown = required; break; }
                grown *= 2U;
            }
            char *next = realloc(data, grown);
            if (next == NULL) { result = HTTP_BODY_NO_MEMORY; goto fail; }
            data = next;
            capacity = grown;
        }
        memcpy(data + used, scratch, (size_t)received);
        used += (size_t)received;
    }
    if (!chunked && declared >= 0 && (uint64_t)declared != used) {
        result = HTTP_BODY_LENGTH_MISMATCH; goto fail;
    }
    if (data == NULL) {
        data = malloc(1);
        if (data == NULL) return HTTP_BODY_NO_MEMORY;
    }
    data[used] = '\0';
    *body = data;
    *length = used;
    return HTTP_BODY_OK;
fail:
    free(data);
    return result;
}

const char *http_body_result_name(http_body_result_t result)
{
    switch (result) {
        case HTTP_BODY_OK: return "ok";
        case HTTP_BODY_ARGUMENT: return "argument";
        case HTTP_BODY_IO: return "io_or_timeout";
        case HTTP_BODY_INCOMPLETE: return "incomplete";
        case HTTP_BODY_NO_MEMORY: return "no_memory";
        case HTTP_BODY_SIZE_OVERFLOW: return "size_overflow";
        case HTTP_BODY_LENGTH_MISMATCH: return "length_mismatch";
        default: return "unknown";
    }
}
