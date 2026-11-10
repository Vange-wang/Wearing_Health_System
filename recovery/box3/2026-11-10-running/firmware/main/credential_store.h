#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    char ssid[33];
    char password[65];
    uint8_t priority;
    uint8_t auth_type;
} wifi_credential_t;

esp_err_t credential_store_load_wifi(wifi_credential_t *out,
                                     size_t capacity,
                                     size_t *count);
esp_err_t credential_store_load_device_token(char *out, size_t capacity);

#ifdef CREDENTIAL_STORE_SELF_TEST
esp_err_t credential_store_selftest(void);
#endif
