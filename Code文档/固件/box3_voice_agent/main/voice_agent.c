/*
 * SPDX-License-Identifier: CC0-1.0
 *
 * voice_agent — v0.4 真机语音终端（WorkBuddy, 2026-08-16）
 *
 * 按键（push-to-talk）：
 *   1. 按住 Boot 键 BSP_BUTTON_CONFIG（GPIO0）→ ES7210 双麦录音（16k/16bit 立体声）
 *   2. 边录边降混为单声道，通过 HTTP chunked 流式上传 PCM 到 voice-bridge
 *   3. 松开按键 → 结束请求流（结束信号）→ 服务端流式 ASR → 返回长度前缀 WAV 帧
 *   4. 逐帧解析（4 字节大端长度 + WAV），跳过 44 字节 WAV 头 → 单声道升混 → ES8311 播放
 *   （复位用硬件 Reset 键，顶部键 GPIO1 为静音键）
 *
 * 依据：2026-08-16-语音桥-spec-v0.4.md（A1 raw PCM、A2 流式 ASR、A3 按键触发）
 * P2（2026-08-23）：BLE central 后台集成（扫描连接腕部节点 + 数据缓存，见 ble_central.c；
 * Boot 键双击触发首次扫描；不阻塞语音首字路径）
 */
#include <math.h>
#include <limits.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "mdns.h"
#include "nvs_flash.h"

#include "bsp/esp-bsp.h"
#include "bsp_board.h"
#include "esp_codec_dev.h"
#include "iot_button.h"
#include "lvgl.h"
#include "cJSON.h"

#include "audio_session.h"
#include "ble_central.h"
#include "credential_store.h"
#include "device_auth_client.h"
#include "wav_stream.h"

static const char *TAG = "voice_agent";

/* ---- 可配置项（按现场改） ---- */
#define SERVER_URL   "http://voicebridge.local:8710/api/v1/voice/stream"
#define HEALTH_URL   "http://voicebridge.local:8710/api/v1/health"
#define ALERT_URL    "http://voicebridge.local:8710/api/v1/health/alert"   /* P4：空闲轮询预警播报 */
#define TALK_BUTTON  BSP_BUTTON_CONFIG   /* Boot 键（GPIO0）：按住说话（顶部键 GPIO1 为静音，复位用硬件 Reset 键） */

/* ---- 屏幕 emoji 状态显示（需求1 替代状态灯，Spec 2026-08-20 §1.3） ---- */
#define EMOJI_OK      "S:/spiffs/emoji_u1f604.png"  /* 大笑 😄：vb可用+WiFi可用 */
#define EMOJI_WIFI_DN "S:/spiffs/emoji_u1f635.png"  /* 晕 😵：vb可用+WiFi不可用 */
#define EMOJI_VB_DN   "S:/spiffs/emoji_u1f910.png"  /* 闭嘴 🤐：vb不可用+WiFi正常 */
#define EMOJI_BOTH_DN "S:/spiffs/emoji_u1f31a.png"  /* 黑脸 🌚：两个都不行 */
#define STATUS_INTERVAL_MS  30000  /* 状态轮询间隔（30s），WiFi 状态变化时立即重判 */
#define HEALTH_TIMEOUT_MS   2000   /* health 轮询超时（2s），超时判 voicebridge 不可用 */

#define MAX_WIFI_CREDS 8

#define SAMPLE_RATE  16000
#define CHANNELS     2                    /* ES7210 双麦立体声 */
#define BITS         16
#define CHUNK_BYTES  4096                 /* 录音/上传分块 */
#define MAX_FRAME    WAV_STREAM_MAX_FRAME_BYTES
#define ALERT_ID_LENGTH 36
#define ALERT_ACK_SUFFIX "/ack"
#define TALK_TASK_STACK_SIZE 4096
#define CAPTURE_TASK_STACK_SIZE 4096

static esp_codec_dev_handle_t s_mic = NULL;
static esp_codec_dev_handle_t s_spk = NULL;

/* 采集与播放使用独立静态 scratch，按键打断预警时不会争用同一缓冲区。 */
static int16_t s_capture_stereo[CHUNK_BYTES / 2];
static int16_t s_capture_mono[CHUNK_BYTES / (CHANNELS * 2)];
static int16_t s_upload_mono[CHUNK_BYTES / (CHANNELS * 2)];
static int16_t s_playback_stereo[CHUNK_BYTES / 2];
static uint8_t s_wav_pcm[CHUNK_BYTES / 2];
static TaskHandle_t s_capture_task_handle = NULL;
static TaskHandle_t s_talk_task_handle = NULL;
static volatile int64_t s_talk_release_us = 0;

/* 屏幕 emoji 状态显示（需求1）：WiFi 状态标志 + LVGL 图片对象 */
static volatile bool s_wifi_up = false;     /* got IP 置 true，disconnected 置 false */
static lv_obj_t *s_emoji_img = NULL;        /* 屏幕 emoji 图片控件 */

/* ---------------- 按键 ---------------- */
static void talk_btn_cb(void *btn_handle, void *usr_data)
{
    button_event_t ev = iot_button_get_event((button_handle_t)btn_handle);
    if (ev == BUTTON_PRESS_DOWN) {
        ESP_LOGI(TAG, "btn PRESS_DOWN -> capture immediately");
        audio_session_begin_capture();
        audio_session_cancel_alert();
        if (s_capture_task_handle != NULL) {
            xTaskNotifyGive(s_capture_task_handle);
        }
        if (s_talk_task_handle != NULL) {
            xTaskNotifyGive(s_talk_task_handle);
        }
    } else if (ev == BUTTON_PRESS_UP) {
        bool short_press = audio_session_cancel_short_press();
        if (!short_press) {
            s_talk_release_us = esp_timer_get_time();
        }
        ESP_LOGI(TAG, "btn PRESS_UP -> %s", short_press ? "discard short capture" : "finish capture");
        if (s_talk_task_handle != NULL) {
            xTaskNotifyGive(s_talk_task_handle);
        }
    }
}

/* P2：Boot 键（GPIO0）双击 → 触发 BLE 首次扫描/配对（已连接则忽略）。
 * 与按住说话不冲突：双击是快速短按两次，说话是按住不放（talk_task 有 300ms 按住守卫）。 */
static void boot_click_cb(void *btn_handle, void *usr_data)
{
    button_event_t ev = iot_button_get_event((button_handle_t)btn_handle);
    if (ev == BUTTON_DOUBLE_CLICK) {
        ESP_LOGI(TAG, "Boot btn DOUBLE_CLICK -> BLE scan trigger");
        ble_central_start_scan();
    }
}

/* ---------------- WiFi ---------------- */
/* 连续重连失败计数：设备长时间运行后 WiFi 可能反复断开重连失败导致"假死"（ping 不通、按键无反应），
   连续失败达到阈值即自动复位（esp_restart），避免需手动按 reset 键。 */
#define WIFI_RECONNECT_FAIL_MAX  10
static int s_wifi_reconnect_fail = 0;

/* 事件组：DISCONNECTED 触发 wifi_task 重新扫描切换；CONNECTED 表示拿到 IP */
static EventGroupHandle_t s_wifi_events;
#define WIFI_BIT_DISCONNECTED  BIT0
#define WIFI_BIT_CONNECTED     BIT1

static volatile bool s_mdns_inited = false;
static volatile bool s_mdns_need_reset = false;   /* WiFi 断开置位，wifi_task 重连前执行 free（不在事件回调里 free，避免阻塞事件循环） */

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "STA start");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED) {
        ESP_LOGI(TAG, "STA connected");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *d = (wifi_event_sta_disconnected_t *)data;
        s_wifi_reconnect_fail++;
        s_wifi_up = false;   /* 需求1：WiFi 掉线，状态任务据此切 emoji */
        ESP_LOGW(TAG, "STA disconnected reason=%d (第 %d 次)", d->reason, s_wifi_reconnect_fail);
        if (s_wifi_reconnect_fail >= WIFI_RECONNECT_FAIL_MAX) {
            ESP_LOGE(TAG, "WiFi 连续断开 %d 次，触发自动复位", s_wifi_reconnect_fail);
            esp_restart();
        }
        /* 需求1（自愈）：WiFi 断开后 mDNS 客户端状态会失效（IP 变化 / 底层 socket 失效），
           需在重连前释放、拿到新 IP 后重新初始化——否则 voicebridge.local 解析永久失败
           （getaddrinfo 202），只能人工复位。
           注意：不在事件回调里直接 mdns_free（会阻塞事件循环），只置标志由 wifi_task 执行。 */
        s_mdns_need_reset = true;
        /* 不在此直接 connect（扫描会阻塞事件循环），通知 wifi_task 重新扫描切换 */
        xEventGroupSetBits(s_wifi_events, WIFI_BIT_DISCONNECTED);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_wifi_reconnect_fail = 0;   /* 拿到 IP 视为连接恢复，清零计数 */
        s_wifi_up = true;            /* 需求1：WiFi 可用 */
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "got IP " IPSTR, IP2STR(&e->ip_info.ip));
        if (!s_mdns_inited) {
            /* mDNS 客户端初始化：让 esp_http_client 能解析 voicebridge.local（配合 LWIP_DNS_SUPPORT_MDNS_QUERIES） */
            if (mdns_init() == ESP_OK) {
                s_mdns_inited = true;
                ESP_LOGI(TAG, "mDNS client init OK");
            }
        }
        xEventGroupSetBits(s_wifi_events, WIFI_BIT_CONNECTED);
    }
}

/* 扫描匹配：选 prio 最小（最高优先），同 prio 取 RSSI 最强；设置 STA 配置并 connect */
static void wifi_scan_and_connect(void)
{
    wifi_credential_t creds[MAX_WIFI_CREDS] = { 0 };
    size_t cred_count = 0;
    esp_err_t credential_err = credential_store_load_wifi(
        creds, MAX_WIFI_CREDS, &cred_count);
    if (credential_err != ESP_OK || cred_count == 0) {
        ESP_LOGE(TAG, "设备未配置 WiFi 凭据，等待本地 NVS 配置");
        return;
    }

    wifi_scan_config_t scan_cfg = {
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time = { .active = { .min = 100, .max = 300 } },
    };
    if (esp_wifi_scan_start(&scan_cfg, true) != ESP_OK) {
        ESP_LOGW(TAG, "WiFi 扫描失败");
        return;
    }
    uint16_t ap_num = 0;
    esp_wifi_scan_get_ap_num(&ap_num);
    if (ap_num == 0) {
        ESP_LOGW(TAG, "未扫到任何 AP");
        return;
    }
    wifi_ap_record_t *aps = calloc(ap_num, sizeof(wifi_ap_record_t));
    if (!aps) {
        return;
    }
    esp_wifi_scan_get_ap_records(&ap_num, aps);

    /* 匹配 + 选最优（prio 升序，同 prio RSSI 降序） */
    int best_cred = -1;
    int best_prio = 255;
    int best_rssi = -128;
    for (int i = 0; i < ap_num; i++) {
        for (size_t c = 0; c < cred_count; c++) {
            if (strcmp((char *)aps[i].ssid, creds[c].ssid) == 0) {
                if (creds[c].priority < best_prio ||
                    (creds[c].priority == best_prio && aps[i].rssi > best_rssi)) {
                    best_prio = creds[c].priority;
                    best_rssi = aps[i].rssi;
                    best_cred = (int)c;
                }
            }
        }
    }
    if (best_cred < 0) {
        ESP_LOGW(TAG, "扫描到 %d 个 AP，无匹配凭据", ap_num);
        free(aps);
        return;
    }

    ESP_LOGI(TAG, "选择连接 ssid=%s rssi=%d prio=%d", creds[best_cred].ssid, best_rssi, best_prio);
    wifi_config_t wc = { 0 };
    size_t ssid_length = strnlen(creds[best_cred].ssid,
                                 sizeof(creds[best_cred].ssid));
    size_t password_length = strnlen(creds[best_cred].password,
                                     sizeof(creds[best_cred].password));
    if (ssid_length == 0 || ssid_length >= sizeof(wc.sta.ssid) ||
        password_length >= sizeof(wc.sta.password)) {
        ESP_LOGE(TAG, "所选 WiFi 凭据长度无效，拒绝连接");
        free(aps);
        return;
    }
    memcpy(wc.sta.ssid, creds[best_cred].ssid, ssid_length);
    wc.sta.ssid[ssid_length] = '\0';
    memcpy(wc.sta.password, creds[best_cred].password, password_length);
    wc.sta.password[password_length] = '\0';
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;  /* 本次全 WPA2（含 iPhone 热点「最大兼容性」） */
    wc.sta.channel = 0;                               /* 信道不固定，自动全信道扫描 */
    wc.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    wc.sta.pmf_cfg.capable = true;                    /* PMF 可选（802.11w） */
    wc.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_connect());
    free(aps);
}

/* WiFi 管理任务：首次扫描连接 + 断开后持续重试扫描直到重连（带指数退避）。
 * 修复：断开后扫描失败（如热点广播尚未恢复、无匹配凭据）时，原实现只扫一次就
 * 回到等待断开事件，而事件位已被消费不会再触发 → 永久卡在断网。现改为内层
 * while(!s_wifi_up) 持续重试，直到 got IP 置 s_wifi_up 才回到等待断开事件。 */
static void wifi_task(void *arg)
{
    while (1) {
        int retry = 0;
        while (!s_wifi_up) {
            /* 断开后 mDNS 状态失效，重连前在任务上下文释放（不阻塞事件循环） */
            if (s_mdns_need_reset && s_mdns_inited) {
                mdns_free();
                s_mdns_inited = false;
                s_mdns_need_reset = false;
                ESP_LOGI(TAG, "mDNS client freed（WiFi 断开，重连后重建）");
            }
            /* 指数退避：首次立即扫，之后 1s/2s/4s/... 封顶 30s */
            if (retry > 0) {
                int shift = retry < 6 ? (retry - 1) : 5;
                int backoff = 1000 << shift;
                if (backoff > 30000) {
                    backoff = 30000;
                }
                ESP_LOGI(TAG, "重连扫描（第 %d 次，退避 %d ms）", retry, backoff);
                vTaskDelay(pdMS_TO_TICKS(backoff));
            } else {
                ESP_LOGI(TAG, "重连扫描（首次/立即）");
            }
            wifi_scan_and_connect();
            /* 等 connect + DHCP 完成（最多 5s），连上则 s_wifi_up 置位退出内层循环 */
            for (int i = 0; i < 10 && !s_wifi_up; i++) {
                vTaskDelay(pdMS_TO_TICKS(500));
            }
            retry++;
        }
        /* 已连接：等待断开事件（断开时置 s_wifi_up=false 唤醒外层循环） */
        xEventGroupWaitBits(s_wifi_events, WIFI_BIT_DISCONNECTED, pdTRUE, pdFALSE, portMAX_DELAY);
    }
}

/* WiFi 初始化：NVS + netif + event + wifi init + start（不阻塞连接） */
static void wifi_init(void)
{
    /* WiFi 需要 NVS 存储配置（esp_wifi_init 前必须初始化） */
    esp_err_t nvs_ret = nvs_flash_init();
    if (nvs_ret == ESP_ERR_NVS_NO_FREE_PAGES || nvs_ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_ret);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL));

    wifi_init_config_t icfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&icfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
}

typedef struct {
    audio_session_owner_t owner;
} codec_output_context_t;

static bool owner_cancelled(void *user)
{
    codec_output_context_t *context = (codec_output_context_t *)user;
    return audio_session_should_cancel(context->owner) ||
           !audio_session_owner_is(context->owner);
}

/* esp_codec_dev_write reports success/error rather than a byte count. Adapt a
 * successful call to an exact full write; wav_stream retries partial writers. */
static int codec_output_write(void *user, const uint8_t *data, size_t length)
{
    codec_output_context_t *context = (codec_output_context_t *)user;
    if (owner_cancelled(user) || length > INT_MAX) {
        return -1;
    }
    int result = esp_codec_dev_write(s_spk, (void *)data, (int)length);
    if (result == 0 && context->owner == AUDIO_SESSION_OWNER_TALK &&
        s_talk_release_us > 0) {
        int64_t release_to_codec_us = esp_timer_get_time() - s_talk_release_us;
        s_talk_release_us = 0;
        ESP_LOGI(TAG, "LATENCY release_to_codec_us=%lld",
                 (long long)release_to_codec_us);
    }
    return result == 0 ? (int)length : -1;
}

static bool http_write_all(esp_http_client_handle_t client, const void *data,
                           size_t length, audio_session_owner_t owner)
{
    const char *bytes = (const char *)data;
    size_t offset = 0;
    while (offset < length) {
        if (audio_session_should_cancel(owner) || !audio_session_owner_is(owner)) {
            return false;
        }
        size_t remaining = length - offset;
        if (remaining > INT_MAX) {
            return false;
        }
        int written = esp_http_client_write(client, bytes + offset, (int)remaining);
        if (written <= 0 || (size_t)written > remaining) {
            return false;
        }
        offset += (size_t)written;
    }
    return true;
}

/* ---------------- 精确读取 n 字节（跨 esp_http_client_read 分片，可被打断） ---------------- */
static bool read_exact(esp_http_client_handle_t client, uint8_t *buf, int n,
                       audio_session_owner_t owner)
{
    int got = 0;
    while (got < n) {
        if (audio_session_should_cancel(owner) || !audio_session_owner_is(owner)) {
            return false;   /* 按键打断 */
        }
        int r = esp_http_client_read(client, (char *)(buf + got), n - got);
        if (r <= 0) {
            return false;   /* EOF / 错误 */
        }
        got += r;
    }
    return true;
}

/* Read one length-prefixed frame header first, validate canonical mono PCM,
 * then stream fixed chunks directly through mono-to-stereo conversion. */
static bool stream_wav_frame(esp_http_client_handle_t client, uint32_t frame_length,
                             audio_session_owner_t owner)
{
    if (frame_length < WAV_STREAM_HEADER_BYTES || frame_length > MAX_FRAME) {
        ESP_LOGE(TAG, "WAV frame length rejected: %u", (unsigned)frame_length);
        return false;
    }

    uint8_t header[WAV_STREAM_HEADER_BYTES];
    if (!read_exact(client, header, sizeof(header), owner)) {
        ESP_LOGE(TAG, "WAV header interrupted");
        return false;
    }

    codec_output_context_t output_context = { .owner = owner };
    wav_stream_t stream;
    wav_stream_result_t result = wav_stream_begin(
        &stream, header, sizeof(header), frame_length, esp_get_free_heap_size(),
        s_playback_stereo, sizeof(s_playback_stereo) / sizeof(s_playback_stereo[0]),
        codec_output_write, owner_cancelled, &output_context);
    if (result != WAV_STREAM_OK) {
        ESP_LOGE(TAG, "WAV header rejected: %s", wav_stream_result_name(result));
        return false;
    }

    uint32_t remaining = frame_length - WAV_STREAM_HEADER_BYTES;
    while (remaining > 0) {
        if (owner_cancelled(&output_context)) {
            result = WAV_STREAM_CANCELLED;
            break;
        }
        size_t wanted = remaining < sizeof(s_wav_pcm) ? remaining : sizeof(s_wav_pcm);
        int received = esp_http_client_read(client, (char *)s_wav_pcm, (int)wanted);
        if (received <= 0) {
            result = WAV_STREAM_TRUNCATED;
            break;
        }
        result = wav_stream_write(&stream, s_wav_pcm, (size_t)received);
        if (result != WAV_STREAM_OK) {
            break;
        }
        remaining -= (uint32_t)received;
    }
    if (result == WAV_STREAM_OK) {
        result = wav_stream_end(&stream);
    }
    if (result != WAV_STREAM_OK) {
        ESP_LOGE(TAG, "WAV stream failed: %s", wav_stream_result_name(result));
        return false;
    }
    return true;
}

/* ---------------- 一轮对话：边录边传（chunked 流式）→ 接收播放 ---------------- */
static void voice_round(uint32_t capture_generation)
{
    /* 1. 创建 HTTP client，open(-1) 触发 Transfer-Encoding: chunked */
    esp_http_client_config_t cfg = {
        .url = SERVER_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 30000,
        .buffer_size = 8192,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        ESP_LOGE(TAG, "http client init FAILED");
        return;
    }
    bool opened = false;
    if (esp_http_client_set_header(client, "Content-Type", "application/octet-stream") != ESP_OK) {
        ESP_LOGE(TAG, "voice content-type header FAILED");
        goto cleanup;
    }
    esp_err_t open_err = open_authenticated_http(client, -1);
    if (open_err != ESP_OK) {
        ESP_LOGE(TAG, "protected voice request unavailable");
        goto cleanup;
    }
    opened = true;

    /* 2. 边录边传：每读一块 PCM，手动 chunk 编码后 write（esp_http_client 不做自动 chunk 编码） */
    ESP_LOGI(TAG, "REC+UPLOAD START (chunked)");
    int uploaded = 0;
    bool upload_ok = true;
    while (!audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK)) {
        size_t samples = audio_session_read_capture(
            s_upload_mono, sizeof(s_upload_mono) / sizeof(s_upload_mono[0]));
        if (samples == 0) {
            if (!audio_session_capture_active() && !audio_session_capture_has_buffered()) {
                break;
            }
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
            continue;
        }
        int wlen = (int)(samples * sizeof(int16_t));
        /* 手动 chunk 编码：size 十六进制行 + 数据 + CRLF */
        char hdr[16];
        int hlen = snprintf(hdr, sizeof(hdr), "%x\r\n", wlen);
        if (hlen <= 0 || hlen >= (int)sizeof(hdr) ||
            !http_write_all(client, hdr, (size_t)hlen, AUDIO_SESSION_OWNER_TALK) ||
            !http_write_all(client, s_upload_mono, (size_t)wlen, AUDIO_SESSION_OWNER_TALK) ||
            !http_write_all(client, "\r\n", 2, AUDIO_SESSION_OWNER_TALK)) {
            ESP_LOGE(TAG, "upload write FAILED");
            upload_ok = false;
            break;
        }
        uploaded += wlen;
    }
    /* 结束 chunk（0 长度 chunk = 按键松开的流结束信号） */
    if (upload_ok && !audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK)) {
        upload_ok = http_write_all(client, "0\r\n\r\n", 5,
                                   AUDIO_SESSION_OWNER_TALK);
    }
    ESP_LOGI(TAG, "REC+UPLOAD END, pcm bytes=%d", uploaded);

    if (!upload_ok || audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK) ||
        capture_generation != audio_session_capture_generation()) {
        goto cleanup;
    }

    /* 3. 读响应头 */
    if (esp_http_client_fetch_headers(client) < 0) {
        ESP_LOGE(TAG, "voice response headers FAILED");
        goto cleanup;
    }
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "HTTP status=%d", status);
    if (status != 200) {
        goto cleanup;
    }

    /* 逐帧解析：4 字节大端长度 + WAV 载荷 */
    uint8_t hdr[4];
    int frames = 0;
    while (read_exact(client, hdr, 4, AUDIO_SESSION_OWNER_TALK)) {
        uint32_t len = ((uint32_t)hdr[0] << 24) | ((uint32_t)hdr[1] << 16) |
                       ((uint32_t)hdr[2] << 8) | (uint32_t)hdr[3];
        if (len < WAV_STREAM_HEADER_BYTES || len > MAX_FRAME) {
            ESP_LOGE(TAG, "bad frame len=%u", (unsigned)len);
            break;
        }
        if (!stream_wav_frame(client, len, AUDIO_SESSION_OWNER_TALK)) {
            break;
        }
        frames++;
    }
    ESP_LOGI(TAG, "PLAY DONE, frames=%d%s", frames,
             audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK) ? " (cancelled)" : "");

cleanup:
    if (opened && esp_http_client_close(client) != ESP_OK) {
        ESP_LOGW(TAG, "voice HTTP close failed");
    }
    if (esp_http_client_cleanup(client) != ESP_OK) {
        ESP_LOGW(TAG, "voice HTTP cleanup failed");
    }
}

/* ---------------- 对话任务：录音上传 + 收帧播放（可被按键打断） ---------------- */
/* 按住守卫：按住不足 MIN_HOLD_MS（300ms）视为双击/单击手势，不发起对话，
 * 避免 Boot 键双击触发 BLE 扫描时产生空 HTTP 请求。 */
#define MIN_HOLD_MS 300

/* 独立高优先级采集任务：按键按下即读麦克风；确认前进入固定预缓冲，
 * 确认后进入有界 live ring。采集循环无 malloc/free。 */
static void capture_task(void *arg)
{
    (void)arg;
    while (true) {
        if (!audio_session_capture_active()) {
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
            continue;
        }

        int r = esp_codec_dev_read(s_mic, (uint8_t *)s_capture_stereo,
                                   sizeof(s_capture_stereo));
        if (r != 0) {
            vTaskDelay(1);
            continue;
        }
        const size_t frames = sizeof(s_capture_stereo) / (CHANNELS * sizeof(int16_t));
        for (size_t i = 0; i < frames; i++) {
            int32_t mixed = (int32_t)s_capture_stereo[i * 2] +
                            s_capture_stereo[i * 2 + 1];
            s_capture_mono[i] = (int16_t)(mixed / 2);
        }
        size_t accepted = audio_session_write_capture(s_capture_mono, frames);
        if (accepted != frames && audio_session_capture_active()) {
            ESP_LOGW(TAG, "capture ring full: accepted=%u/%u", (unsigned)accepted,
                     (unsigned)frames);
        }

        if (audio_session_capture_pending() &&
            audio_session_capture_elapsed_us() >= MIN_HOLD_MS * 1000LL &&
            audio_session_confirm_long_press()) {
            ESP_LOGI(TAG, "long press confirmed; prebuffer ready");
            if (s_talk_task_handle != NULL) {
                xTaskNotifyGive(s_talk_task_handle);
            }
        } else if (audio_session_capture_confirmed() &&
                   s_talk_task_handle != NULL) {
            xTaskNotifyGive(s_talk_task_handle);
        }
    }
}

static void talk_task(void *arg)
{
    (void)arg;
    while (true) {
        if (!audio_session_capture_confirmed()) {
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
            continue;
        }
        uint32_t generation = audio_session_capture_generation();
        while (!audio_session_acquire_playback(AUDIO_SESSION_OWNER_TALK)) {
            if (generation != audio_session_capture_generation() ||
                !audio_session_capture_confirmed()) {
                break;
            }
            vTaskDelay(1);
        }
        if (!audio_session_owner_is(AUDIO_SESSION_OWNER_TALK) ||
            generation != audio_session_capture_generation()) {
            audio_session_release(AUDIO_SESSION_OWNER_TALK);
            continue;
        }
        ESP_LOGI(TAG, ">> TALK START");
        voice_round(generation);
        audio_session_release(AUDIO_SESSION_OWNER_TALK);
        audio_session_complete_capture(generation);
        ESP_LOGI(TAG, "talk stack high-water remaining=%u bytes",
                 (unsigned)uxTaskGetStackHighWaterMark(NULL));
        ESP_LOGI(TAG, "<< TALK DONE");
    }
}

static bool valid_alert_id(const char *alert_id)
{
    if (alert_id == NULL || strlen(alert_id) != ALERT_ID_LENGTH) {
        return false;
    }
    for (size_t i = 0; i < ALERT_ID_LENGTH; ++i) {
        bool hyphen_position = i == 8 || i == 13 || i == 18 || i == 23;
        if (hyphen_position ? alert_id[i] != '-' : !isxdigit((unsigned char)alert_id[i])) {
            return false;
        }
    }
    return true;
}

typedef struct {
    char alert_id[ALERT_ID_LENGTH + 1];
} alert_response_context_t;

static esp_err_t alert_http_event(esp_http_client_event_t *event)
{
    alert_response_context_t *context = (alert_response_context_t *)event->user_data;
    if (context != NULL && event->event_id == HTTP_EVENT_ON_HEADER &&
        event->header_key != NULL && event->header_value != NULL &&
        strcasecmp(event->header_key, "X-Alert-ID") == 0) {
        size_t length = strnlen(event->header_value, ALERT_ID_LENGTH + 1);
        if (length == ALERT_ID_LENGTH) {
            memcpy(context->alert_id, event->header_value, ALERT_ID_LENGTH);
            context->alert_id[ALERT_ID_LENGTH] = '\0';
        }
    }
    return ESP_OK;
}

static bool post_alert_ack(const char *alert_id)
{
    if (!valid_alert_id(alert_id)) {
        return false;
    }
    char url[sizeof(ALERT_URL) + ALERT_ID_LENGTH + sizeof(ALERT_ACK_SUFFIX) + 1];
    int length = snprintf(url, sizeof(url), "%s/%s%s", ALERT_URL, alert_id,
                          ALERT_ACK_SUFFIX);
    if (length <= 0 || length >= (int)sizeof(url)) {
        return false;
    }
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 5000,
        .buffer_size = 512,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client == NULL) {
        return false;
    }
    bool opened = false;
    bool acknowledged = false;
    if (open_authenticated_http(client, 0) == ESP_OK) {
        opened = true;
        if (esp_http_client_fetch_headers(client) >= 0 &&
            esp_http_client_get_status_code(client) == 200) {
            acknowledged = true;
        }
    }
    if (opened && esp_http_client_close(client) != ESP_OK) {
        acknowledged = false;
    }
    if (esp_http_client_cleanup(client) != ESP_OK) {
        acknowledged = false;
    }
    ESP_LOGI(TAG, "ALERT ack id=%s result=%s", alert_id,
             acknowledged ? "ok" : "failed");
    return acknowledged;
}

/* ---------------- P4 预警空闲轮询（Spec 方案 A：不打断对话，30s/次） ---------------- */
#define ALERT_POLL_INTERVAL_MS 30000

/* 单次轮询：200 → 逐帧播放（长度前缀 WAV，复用语音帧协议）；204/网络失败 → 静默返回 */
static void alert_poll_once(void)
{
    alert_response_context_t response_context = { 0 };
    esp_http_client_config_t cfg = {
        .url = ALERT_URL,
        .method = HTTP_METHOD_GET,
        .timeout_ms = 5000,
        .buffer_size = 1024,
        .event_handler = alert_http_event,
        .user_data = &response_context,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        return;
    }
    bool opened = false;
    bool playback_complete = false;
    char alert_id[ALERT_ID_LENGTH + 1] = { 0 };
    if (open_authenticated_http(client, 0) != ESP_OK) {
        goto cleanup;
    }
    opened = true;
    if (esp_http_client_fetch_headers(client) < 0) {
        goto cleanup;
    }
    int status = esp_http_client_get_status_code(client);
    if (status == 200 && audio_session_owner_is(AUDIO_SESSION_OWNER_ALERT) &&
        !audio_session_should_cancel(AUDIO_SESSION_OWNER_ALERT)) {
        if (!valid_alert_id(response_context.alert_id)) {
            ESP_LOGE(TAG, "ALERT response missing/invalid X-Alert-ID");
            goto cleanup;
        }
        memcpy(alert_id, response_context.alert_id, ALERT_ID_LENGTH);
        alert_id[ALERT_ID_LENGTH] = '\0';
        ESP_LOGI(TAG, "ALERT 有预警，开始播报");
        uint8_t hdr[4];
        int frames = 0;
        bool stream_ok = true;
        while (read_exact(client, hdr, 4, AUDIO_SESSION_OWNER_ALERT)) {
            uint32_t len = ((uint32_t)hdr[0] << 24) | ((uint32_t)hdr[1] << 16) |
                           ((uint32_t)hdr[2] << 8) | (uint32_t)hdr[3];
            if (len < WAV_STREAM_HEADER_BYTES || len > MAX_FRAME) {
                ESP_LOGE(TAG, "ALERT bad frame len=%u", (unsigned)len);
                stream_ok = false;
                break;
            }
            if (!stream_wav_frame(client, len, AUDIO_SESSION_OWNER_ALERT)) {
                stream_ok = false;
                break;   /* 按键打断 */
            }
            frames++;
        }
        playback_complete = stream_ok && frames > 0 &&
                            !audio_session_should_cancel(AUDIO_SESSION_OWNER_ALERT) &&
                            audio_session_owner_is(AUDIO_SESSION_OWNER_ALERT) &&
                            esp_http_client_is_complete_data_received(client);
        ESP_LOGI(TAG, "ALERT PLAY DONE frames=%d", frames);
    }
cleanup:
    if (opened && esp_http_client_close(client) != ESP_OK) {
        ESP_LOGW(TAG, "alert HTTP close failed");
    }
    if (esp_http_client_cleanup(client) != ESP_OK) {
        ESP_LOGW(TAG, "alert HTTP cleanup failed");
    }
    if (playback_complete) {
        post_alert_ack(alert_id);
    }
}

/* 空闲轮询任务：WiFi 可用且无对话进行中才轮询；播报可被按键打断 */
static void alert_poll_task(void *arg)
{
    (void)arg;
    while (1) {
        if (s_wifi_up && audio_session_acquire_playback(AUDIO_SESSION_OWNER_ALERT)) {
            alert_poll_once();
            audio_session_release(AUDIO_SESSION_OWNER_ALERT);
        }
        vTaskDelay(pdMS_TO_TICKS(ALERT_POLL_INTERVAL_MS));
    }
}

/* ---------------- 屏幕 emoji 状态显示（需求1，Spec §1.3） ---------------- */

/* 初始化屏幕 + LVGL（照抄 image_display.c app_main，LVGL 9.5 已验证）。
 * 在 bsp_i2c_init() 之后调用；SPIFFS 挂载 + 显示 + 背光 + 创建 emoji 图片控件。 */
static void display_init(void)
{
    bsp_display_cfg_t cfg = {
        .lvgl_port_cfg = ESP_LVGL_PORT_INIT_CONFIG(),
        .buffer_size = BSP_LCD_H_RES * CONFIG_BSP_LCD_DRAW_BUF_HEIGHT,
        .double_buffer = 0,
        .flags = { .buff_dma = true },
    };
    bsp_display_start_with_config(&cfg);
    bsp_display_backlight_on();
    bsp_spiffs_mount();

    if (bsp_display_lock(5000)) {
        s_emoji_img = lv_img_create(lv_scr_act());
        lv_obj_align(s_emoji_img, LV_ALIGN_CENTER, 0, 0);
        bsp_display_unlock();
        ESP_LOGI(TAG, "display init OK: emoji widget created");
    } else {
        ESP_LOGE(TAG, "bsp_display_lock TIMEOUT - emoji widget not created");
    }
}

/* 轮询 voicebridge /api/v1/health，返回 tts.last_probe_ok（true=可用，false/失败=不可用）。
 * 用 esp_http_client 直连，超时 2s；响应体小（<1KB），一次读完。 */
static bool health_probe_ok(void)
{
    esp_http_client_config_t cfg = {
        .url = HEALTH_URL,
        .method = HTTP_METHOD_GET,
        .timeout_ms = HEALTH_TIMEOUT_MS,
        .buffer_size = 1024,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        return false;
    }
    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }
    int len = esp_http_client_fetch_headers(client);
    if (len < 0) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }
    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }

    char buf[512];
    int total = 0;
    int r;
    bool ok = false;
    while (total < (int)sizeof(buf) - 1) {
        r = esp_http_client_read(client, buf + total, sizeof(buf) - 1 - total);
        if (r <= 0) {
            break;
        }
        total += r;
    }
    buf[total] = '\0';
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        return false;
    }
    cJSON *tts = cJSON_GetObjectItem(root, "tts");
    if (tts) {
        cJSON *probe = cJSON_GetObjectItem(tts, "last_probe_ok");
        if (probe && cJSON_IsBool(probe)) {
            ok = cJSON_IsTrue(probe);
        }
    }
    cJSON_Delete(root);
    return ok;
}

/* 切换 emoji：必须在 LVGL 锁内调 lv_img_set_src（避免与渲染任务竞争）。 */
static void emoji_show(const char *path)
{
    if (s_emoji_img == NULL) {
        return;
    }
    if (bsp_display_lock(5000)) {
        lv_img_set_src(s_emoji_img, path);
        lv_obj_align(s_emoji_img, LV_ALIGN_CENTER, 0, 0);
        bsp_display_unlock();
    }
}

/* 状态任务：每 30s 轮询 health + 判 WiFi，切 4 态 emoji；WiFi 状态变化时立即重判。 */
static void status_task(void *arg)
{
    (void)arg;
    const char *cur = NULL;
    bool last_wifi = !s_wifi_up;   /* 首次强制判定一次 */
    bool vb_last = false;          /* WiFi 正常时最后一次 vb 探测结果（WiFi 断时用缓存，避免必失败探测吞掉 😵 态） */

    while (true) {
        bool wifi = s_wifi_up;
        bool vb_ok;
        if (wifi) {
            /* WiFi 正常才探测 vb，并缓存结果 */
            vb_ok = health_probe_ok();
            vb_last = vb_ok;
        } else {
            /* WiFi 断 → 无法探测 vb，用上次缓存（vb 服务仍在但网络断 → 😵；服务也坏 → 🌚） */
            vb_ok = vb_last;
        }
        const char *next;
        if (wifi && vb_ok) {
            next = EMOJI_OK;        /* 😄 */
        } else if (vb_ok) {
            next = EMOJI_WIFI_DN;   /* 😵 */
        } else if (wifi) {
            next = EMOJI_VB_DN;     /* 🤐 */
        } else {
            next = EMOJI_BOTH_DN;   /* 🌚 */
        }

        if (cur == NULL || strcmp(cur, next) != 0 || wifi != last_wifi) {
            ESP_LOGI(TAG, "status: wifi=%d vb=%d -> emoji %s", wifi, vb_ok, strrchr(next, '/') ? strrchr(next, '/') + 1 : next);
            emoji_show(next);
            cur = next;
        }
        last_wifi = wifi;

        /* 30s 轮询；WiFi 状态变化时（last_wifi 已更新）下一轮立即重判 */
        vTaskDelay(pdMS_TO_TICKS(STATUS_INTERVAL_MS));
    }
}

/* ---------------- 主入口 ---------------- */
void app_main(void)
{
    ESP_LOGI(TAG, "=== voice_agent boot (v0.4) ===");

#ifdef CREDENTIAL_STORE_SELF_TEST
    ESP_ERROR_CHECK(credential_store_selftest());
#endif
#ifdef DEVICE_AUTH_CLIENT_SELF_TEST
    ESP_ERROR_CHECK(device_auth_client_selftest());
#endif

    /* 音频（I2S + ES7210 录音 + ES8311 播放）—— 复用 M0 V-04/V-05 已验证配置 */
    ESP_ERROR_CHECK(bsp_i2c_init());
    i2s_std_config_t i2s_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = BSP_I2S_MCLK,
            .bclk = BSP_I2S_SCLK,
            .ws   = BSP_I2S_LCLK,
            .dout = BSP_I2S_DOUT,
            .din  = BSP_I2S_DSIN,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_ERROR_CHECK(bsp_audio_init(&i2s_cfg));
    s_spk = bsp_audio_codec_speaker_init();
    s_mic = bsp_audio_codec_microphone_init();
    if (!s_spk || !s_mic) {
        ESP_LOGE(TAG, "codec init FAILED spk=%p mic=%p", s_spk, s_mic);
        return;
    }

    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = BITS,
        .channel = CHANNELS,
        .sample_rate = SAMPLE_RATE,
    };
    esp_codec_dev_set_out_vol(s_spk, 70);
    esp_codec_dev_set_in_gain(s_mic, 30.0f);
    if (esp_codec_dev_open(s_spk, &fs) != 0 || esp_codec_dev_open(s_mic, &fs) != 0) {
        ESP_LOGE(TAG, "codec open FAILED");
        return;
    }
    ESP_LOGI(TAG, "codecs open OK: %d Hz %d ch %d bit", SAMPLE_RATE, CHANNELS, BITS);
    audio_session_init();

    /* 屏幕 emoji 状态显示（需求1）：在 WiFi 之前初始化，WiFi 就绪后启动状态任务 */
    display_init();

    /* WiFi：初始化 + 管理任务（扫描连接 + 断开重连切换），等首次拿到 IP 再进入交互 */
    s_wifi_events = xEventGroupCreate();
    wifi_init();
    esp_err_t auth_ret = device_auth_client_init();
    if (auth_ret != ESP_OK) {
        ESP_LOGE(TAG, "device authentication unavailable; protected requests disabled");
    } else {
        ESP_LOGI(TAG, "device authentication ready");
    }
    xTaskCreate(wifi_task, "wifi", 4096, NULL, 5, NULL);
    xEventGroupWaitBits(s_wifi_events, WIFI_BIT_CONNECTED, pdFALSE, pdFALSE, pdMS_TO_TICKS(30000));

    /* 屏幕 emoji 状态任务（低优先级，30s 轮询 + WiFi 状态变化即时重判） */
    BaseType_t status_task_result = xTaskCreate(
        status_task, "status", 4096, NULL, 4, NULL);
    if (status_task_result != pdPASS) {
        ESP_LOGE(TAG, "status task create FAILED rc=%ld",
                 (long)status_task_result);
    }

    /* 按键：Boot 键（GPIO0=CONFIG）按住说话、双击触发 BLE 扫描（P2）。
     * 复位用硬件 Reset 键（无需软件处理）。 */
    bsp_btn_init();
    bsp_btn_register_callback(BSP_BUTTON_CONFIG, BUTTON_PRESS_DOWN, talk_btn_cb, NULL);
    bsp_btn_register_callback(BSP_BUTTON_CONFIG, BUTTON_PRESS_UP, talk_btn_cb, NULL);
    bsp_btn_register_callback(BSP_BUTTON_CONFIG, BUTTON_DOUBLE_CLICK, boot_click_cb, NULL);
    ESP_LOGI(TAG, "push-to-talk ready: hold Boot button to speak");

    /* P2：BLE central 后台初始化（NimBLE 主机任务 + 重连任务，不阻塞语音） */
    esp_err_t ble_ret = ble_central_init();
    if (ble_ret != ESP_OK) {
        ESP_LOGE(TAG, "BLE central init FAILED rc=%d", ble_ret);
    }

    /* NimBLE 先保留内部内存；后台上传栈已放入 PSRAM，再创建语音关键任务。 */
    ESP_LOGI(TAG, "before voice tasks: internal_free=%u largest=%u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(
                 MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    BaseType_t talk_task_result = xTaskCreate(
        talk_task, "talk", TALK_TASK_STACK_SIZE, NULL, 5, &s_talk_task_handle);
    if (talk_task_result != pdPASS) {
        ESP_LOGE(TAG, "talk task create FAILED rc=%ld", (long)talk_task_result);
    }

    BaseType_t capture_task_result = xTaskCreate(
        capture_task, "capture", CAPTURE_TASK_STACK_SIZE, NULL, 6,
        &s_capture_task_handle);
    if (capture_task_result != pdPASS) {
        ESP_LOGE(TAG, "capture task create FAILED rc=%ld",
                 (long)capture_task_result);
    }

    /* P4：低优先级预警轮询不在首字路径，其栈使用 PSRAM，保留关键任务内部栈。 */
    BaseType_t alert_task_result = xTaskCreateWithCaps(
        alert_poll_task, "alert_poll", 4096, NULL, 4, NULL,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (alert_task_result != pdPASS) {
        ESP_LOGE(TAG, "alert task create FAILED rc=%ld",
                 (long)alert_task_result);
    }
}
