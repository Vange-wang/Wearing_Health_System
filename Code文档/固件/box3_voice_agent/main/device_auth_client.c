#include "device_auth_client.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "credential_store.h"


#define DEVICE_TOKEN_CAPACITY 256

typedef esp_err_t (*device_token_loader_fn)(char *out, size_t capacity);

static char s_device_token[DEVICE_TOKEN_CAPACITY];
static bool s_device_token_ready;


static esp_err_t device_auth_client_init_with_loader(device_token_loader_fn loader)
{
    memset(s_device_token, 0, sizeof(s_device_token));
    s_device_token_ready = false;
    if (loader == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t err = loader(s_device_token, sizeof(s_device_token));
    if (err != ESP_OK || s_device_token[0] == '\0') {
        memset(s_device_token, 0, sizeof(s_device_token));
        return err == ESP_OK ? ESP_ERR_NOT_FOUND : err;
    }
    s_device_token[sizeof(s_device_token) - 1] = '\0';
    s_device_token_ready = true;
    return ESP_OK;
}


esp_err_t device_auth_client_init(void)
{
    return device_auth_client_init_with_loader(credential_store_load_device_token);
}


esp_err_t add_device_auth_header(esp_http_client_handle_t client)
{
    if (!s_device_token_ready || s_device_token[0] == '\0') {
        return ESP_ERR_NOT_FOUND;
    }
    if (client == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    return esp_http_client_set_header(client, "X-Device-Token", s_device_token);
}


esp_err_t open_authenticated_http(esp_http_client_handle_t client, int write_len)
{
    esp_err_t err = add_device_auth_header(client);
    if (err != ESP_OK) {
        return err;
    }
    return esp_http_client_open(client, write_len);
}


#ifdef DEVICE_AUTH_CLIENT_SELF_TEST
static esp_err_t missing_token_loader(char *out, size_t capacity)
{
    if (out != NULL && capacity > 0) {
        out[0] = '\0';
    }
    return ESP_ERR_NOT_FOUND;
}


esp_err_t device_auth_client_selftest(void)
{
    if (device_auth_client_init_with_loader(missing_token_loader) !=
        ESP_ERR_NOT_FOUND) {
        return ESP_FAIL;
    }

    /* A sentinel handle is safe here only if the missing-token gate prevents open. */
    esp_http_client_handle_t sentinel = (esp_http_client_handle_t)(uintptr_t)1;
    if (open_authenticated_http(sentinel, 0) != ESP_ERR_NOT_FOUND) {
        return ESP_FAIL;
    }
    return ESP_OK;
}
#endif
