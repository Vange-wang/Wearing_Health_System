#pragma once

#include "esp_err.h"
#include "esp_http_client.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>


/* Load the device token once after NVS initialization. */
esp_err_t device_auth_client_init(void);

/* Add the protected-device header without logging or exposing its value. */
esp_err_t add_device_auth_header(esp_http_client_handle_t client);

/* Add authentication first; the HTTP connection is never opened on failure. */
esp_err_t open_authenticated_http(esp_http_client_handle_t client, int write_len);

/* Domain-limited discovery operations; never expose raw token/derived key. */
bool device_auth_discovery_ready(void);
bool device_auth_discovery_mac(const uint8_t *prefix,size_t size,uint8_t out[32]);
bool device_auth_discovery_verify(const uint8_t prefix[50],const uint8_t mac[32]);
#ifdef DEVICE_AUTH_DISCOVERY_SELF_TEST
/* Only public fake RFC/protocol vectors. Never replaces the live auth state. */
bool device_auth_discovery_selftest(void);
#endif

#ifdef DEVICE_AUTH_CLIENT_SELF_TEST
esp_err_t device_auth_client_selftest(void);
#endif
