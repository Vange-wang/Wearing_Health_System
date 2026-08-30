#pragma once

#include "esp_err.h"
#include "esp_http_client.h"


/* Load the device token once after NVS initialization. */
esp_err_t device_auth_client_init(void);

/* Add the protected-device header without logging or exposing its value. */
esp_err_t add_device_auth_header(esp_http_client_handle_t client);

/* Add authentication first; the HTTP connection is never opened on failure. */
esp_err_t open_authenticated_http(esp_http_client_handle_t client, int write_len);

#ifdef DEVICE_AUTH_CLIENT_SELF_TEST
esp_err_t device_auth_client_selftest(void);
#endif
