#include "credential_store.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "nvs.h"

#define CREDENTIAL_NAMESPACE "voice_cfg"
#define MAX_WIFI_CREDENTIALS 8

static const char *TAG = "credential_store";

typedef esp_err_t (*credential_read_u8_fn)(void *context,
                                           const char *key,
                                           uint8_t *value);
typedef esp_err_t (*credential_read_string_fn)(void *context,
                                               const char *key,
                                               char *out,
                                               size_t capacity);

typedef struct {
    void *context;
    credential_read_u8_fn read_u8;
    credential_read_string_fn read_string;
} credential_reader_t;

esp_err_t credential_store_load_wifi_with_reader(
    const credential_reader_t *reader,
    wifi_credential_t *out,
    size_t capacity,
    size_t *count);

static bool make_key(char *out, size_t capacity, const char *prefix, size_t index)
{
    int written = snprintf(out, capacity, "%s_%u", prefix, (unsigned)index);
    return written > 0 && (size_t)written < capacity;
}

esp_err_t credential_store_load_wifi_with_reader(
    const credential_reader_t *reader,
    wifi_credential_t *out,
    size_t capacity,
    size_t *count)
{
    if (reader == NULL || reader->read_u8 == NULL ||
        reader->read_string == NULL || out == NULL || count == NULL ||
        capacity == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    *count = 0;

    uint8_t stored_count = 0;
    esp_err_t err = reader->read_u8(reader->context, "count", &stored_count);
    if (err != ESP_OK) {
        return err == ESP_ERR_NOT_FOUND ? ESP_ERR_NOT_FOUND : err;
    }
    size_t limit = stored_count;
    if (limit > MAX_WIFI_CREDENTIALS) {
        limit = MAX_WIFI_CREDENTIALS;
    }

    for (size_t index = 0; index < limit && *count < capacity; ++index) {
        wifi_credential_t candidate = { 0 };
        char ssid_key[16];
        char password_key[16];
        char priority_key[16];
        char auth_key[16];
        if (!make_key(ssid_key, sizeof(ssid_key), "ssid", index) ||
            !make_key(password_key, sizeof(password_key), "pass", index) ||
            !make_key(priority_key, sizeof(priority_key), "prio", index) ||
            !make_key(auth_key, sizeof(auth_key), "auth", index)) {
            ESP_LOGW(TAG, "credential index=%u key formatting failed",
                     (unsigned)index);
            continue;
        }

        if (reader->read_string(reader->context, ssid_key,
                                candidate.ssid, sizeof(candidate.ssid)) != ESP_OK ||
            reader->read_string(reader->context, password_key,
                                candidate.password,
                                sizeof(candidate.password)) != ESP_OK ||
            reader->read_u8(reader->context, priority_key,
                            &candidate.priority) != ESP_OK ||
            reader->read_u8(reader->context, auth_key,
                            &candidate.auth_type) != ESP_OK) {
            ESP_LOGW(TAG, "credential index=%u missing or invalid",
                     (unsigned)index);
            continue;
        }
        candidate.ssid[sizeof(candidate.ssid) - 1] = '\0';
        candidate.password[sizeof(candidate.password) - 1] = '\0';
        if (candidate.ssid[0] == '\0') {
            ESP_LOGW(TAG, "credential index=%u has empty SSID", (unsigned)index);
            continue;
        }
        out[*count] = candidate;
        ++(*count);
    }
    return *count > 0 ? ESP_OK : ESP_ERR_NOT_FOUND;
}

typedef struct {
    nvs_handle_t handle;
} nvs_reader_context_t;

static esp_err_t normalize_nvs_error(esp_err_t err)
{
    return err == ESP_ERR_NVS_NOT_FOUND ? ESP_ERR_NOT_FOUND : err;
}

static esp_err_t nvs_reader_read_u8(void *context,
                                    const char *key,
                                    uint8_t *value)
{
    nvs_reader_context_t *nvs_context = context;
    return normalize_nvs_error(nvs_get_u8(nvs_context->handle, key, value));
}

static esp_err_t nvs_reader_read_string(void *context,
                                        const char *key,
                                        char *out,
                                        size_t capacity)
{
    nvs_reader_context_t *nvs_context = context;
    size_t length = capacity;
    esp_err_t err = nvs_get_str(nvs_context->handle, key, out, &length);
    if (err == ESP_ERR_NVS_INVALID_LENGTH) {
        return ESP_ERR_INVALID_SIZE;
    }
    return normalize_nvs_error(err);
}

esp_err_t credential_store_load_wifi(wifi_credential_t *out,
                                     size_t capacity,
                                     size_t *count)
{
    if (count != NULL) {
        *count = 0;
    }
    if (out == NULL || count == NULL || capacity == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle;
    esp_err_t err = nvs_open(CREDENTIAL_NAMESPACE, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        return normalize_nvs_error(err);
    }
    nvs_reader_context_t context = { .handle = handle };
    credential_reader_t reader = {
        .context = &context,
        .read_u8 = nvs_reader_read_u8,
        .read_string = nvs_reader_read_string,
    };
    err = credential_store_load_wifi_with_reader(
        &reader, out, capacity, count);
    nvs_close(handle);
    return err;
}

esp_err_t credential_store_load_device_token(char *out, size_t capacity)
{
    if (out == NULL || capacity < 2) {
        return ESP_ERR_INVALID_ARG;
    }
    out[0] = '\0';
    nvs_handle_t handle;
    esp_err_t err = nvs_open(CREDENTIAL_NAMESPACE, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        return normalize_nvs_error(err);
    }
    size_t length = capacity;
    err = nvs_get_str(handle, "device_token", out, &length);
    nvs_close(handle);
    if (err == ESP_ERR_NVS_INVALID_LENGTH) {
        out[0] = '\0';
        return ESP_ERR_INVALID_SIZE;
    }
    err = normalize_nvs_error(err);
    if (err != ESP_OK || length <= 1 || out[0] == '\0') {
        out[0] = '\0';
        return err == ESP_OK ? ESP_ERR_NOT_FOUND : err;
    }
    out[capacity - 1] = '\0';
    return ESP_OK;
}

#ifdef CREDENTIAL_STORE_SELF_TEST
static esp_err_t fake_read_u8(void *context, const char *key, uint8_t *value)
{
    (void)context;
    if (strcmp(key, "count") == 0) {
        *value = 3;
        return ESP_OK;
    }
    if (strcmp(key, "prio_0") == 0 || strcmp(key, "auth_0") == 0) {
        *value = 0;
        return ESP_OK;
    }
    if (strcmp(key, "prio_2") == 0 || strcmp(key, "auth_2") == 0) {
        *value = 2;
        return ESP_OK;
    }
    return ESP_ERR_NOT_FOUND;
}

static esp_err_t fake_read_string(void *context,
                                  const char *key,
                                  char *out,
                                  size_t capacity)
{
    (void)context;
    const char *value = NULL;
    if (strcmp(key, "ssid_0") == 0) {
        value = "test-0";
    } else if (strcmp(key, "pass_0") == 0) {
        value = "password-0";
    } else if (strcmp(key, "ssid_2") == 0) {
        value = "test-2";
    } else if (strcmp(key, "pass_2") == 0) {
        value = "password-2";
    } else {
        return ESP_ERR_NOT_FOUND;
    }
    size_t needed = strlen(value) + 1;
    if (needed > capacity) {
        return ESP_ERR_INVALID_SIZE;
    }
    memcpy(out, value, needed);
    return ESP_OK;
}

esp_err_t credential_store_selftest(void)
{
    credential_reader_t reader = {
        .context = NULL,
        .read_u8 = fake_read_u8,
        .read_string = fake_read_string,
    };
    wifi_credential_t out[3] = { 0 };
    size_t count = 0;
    esp_err_t err = credential_store_load_wifi_with_reader(
        &reader, out, 3, &count);
    if (err != ESP_OK || count != 2 ||
        strcmp(out[0].ssid, "test-0") != 0 ||
        strcmp(out[1].ssid, "test-2") != 0) {
        return ESP_FAIL;
    }
    return ESP_OK;
}
#endif
