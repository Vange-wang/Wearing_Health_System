/*
 * SPDX-License-Identifier: CC0-1.0
 *
 * voice_agent — v0.4 真机语音终端（WorkBuddy, 2026-08-16）
 *
 * 按键按住说话（push-to-talk）：
 *   1. 按住 BSP_BUTTON_CONFIG（GPIO0）→ ES7210 双麦录音（16k/16bit 立体声）
 *   2. 边录边降混为单声道，通过 HTTP chunked 流式上传 PCM 到 voice-bridge
 *   3. 松开按键 → 结束请求流（结束信号）→ 服务端流式 ASR → 返回长度前缀 WAV 帧
 *   4. 逐帧解析（4 字节大端长度 + WAV），跳过 44 字节 WAV 头 → 单声道升混 → ES8311 播放
 *
 * 依据：2026-08-16-语音桥-spec-v0.4.md（A1 raw PCM、A2 流式 ASR、A3 按键触发）
 */
#include <math.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "mdns.h"
#include "nvs_flash.h"

#include "bsp/esp-bsp.h"
#include "bsp_board.h"
#include "esp_codec_dev.h"
#include "iot_button.h"

static const char *TAG = "voice_agent";

/* ---- 可配置项（按现场改） ---- */
#define SERVER_URL   "http://voicebridge.local:8710/api/v1/voice/stream"
#define TALK_BUTTON  BSP_BUTTON_MUTE     /* GPIO1 顶部圆键：按住说话 */

/* ---- 多 WiFi 凭据（Spec 2026-08-18：预置三组，NVS 存储，v2 优先） ---- */
#define MAX_WIFI_CREDS      8            /* 预留扩展位（本次用 3 组） */
#define WIFI_NVS_NAMESPACE  "wifi_cfg"
#define WIFI_NVS_COUNT_KEY  "count"
#define WIFI_NVS_ENTRY_KEY  "cred_%d"

#define WIFI_AUTH_WPA2_PSK_T  0          /* 预留：未来校园网网页认证填 portal */

typedef struct {
    char ssid[33];        /* SSID 最长 32 字节 */
    char pass[65];        /* 密码最长 64 字节 */
    uint8_t prio;         /* 优先级，小值优先（1 最高） */
    uint8_t auth_type;    /* 预留扩展位（本次全 WPA2-PSK） */
} wifi_cred_t;

/* 默认三组凭据（首次启动写入 NVS；之后改网络改 NVS 不重烧固件）。
 * 密码已脱敏（占位符）：实际部署时在此填入，或首次启动后改 NVS。 */
static const wifi_cred_t DEFAULT_WIFI_CREDS[3] = {
    { "v2",     "WIFI_PASS_V2",     1, WIFI_AUTH_WPA2_PSK_T },
    { "2702",   "WIFI_PASS_HOME_1", 2, WIFI_AUTH_WPA2_PSK_T },
    { "L1122S", "WIFI_PASS_HOME_2", 3, WIFI_AUTH_WPA2_PSK_T },
};

#define SAMPLE_RATE  16000
#define CHANNELS     2                    /* ES7210 双麦立体声 */
#define BITS         16
#define CHUNK_BYTES  4096                 /* 录音/上传分块 */
#define MAX_FRAME    2 * 1024 * 1024      /* 单帧守卫（对齐服务端 8MB，本地更小） */
#define WAV_HEADER   44

static esp_codec_dev_handle_t s_mic = NULL;
static esp_codec_dev_handle_t s_spk = NULL;
static volatile bool s_recording = false;
static volatile bool s_cancel = false;      /* 打断当前播放（按键按下时置位） */

/* 静态 scratch 缓冲（单线程任务内，避免栈溢出） */
static int16_t s_stereo[CHUNK_BYTES / 2];   /* 录音立体声分块 */
static int16_t s_mono[CHUNK_BYTES / 2];     /* 降混单声道分块 */

/* ---------------- 按键 ---------------- */
static void talk_btn_cb(void *btn_handle, void *usr_data)
{
    button_event_t ev = iot_button_get_event((button_handle_t)btn_handle);
    if (ev == BUTTON_PRESS_DOWN) {
        ESP_LOGI(TAG, "btn PRESS_DOWN -> start recording");
        s_recording = true;
        s_cancel = true;   /* 打断当前播放（若有），长回复期间按键可响应 */
    } else if (ev == BUTTON_PRESS_UP) {
        ESP_LOGI(TAG, "btn PRESS_UP -> stop recording");
        s_recording = false;
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

static bool s_mdns_inited = false;

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "STA start");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED) {
        ESP_LOGI(TAG, "STA connected");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *d = (wifi_event_sta_disconnected_t *)data;
        s_wifi_reconnect_fail++;
        ESP_LOGW(TAG, "STA disconnected reason=%d (第 %d 次)", d->reason, s_wifi_reconnect_fail);
        if (s_wifi_reconnect_fail >= WIFI_RECONNECT_FAIL_MAX) {
            ESP_LOGE(TAG, "WiFi 连续断开 %d 次，触发自动复位", s_wifi_reconnect_fail);
            esp_restart();
        }
        /* 不在此直接 connect（扫描会阻塞事件循环），通知 wifi_task 重新扫描切换 */
        xEventGroupSetBits(s_wifi_events, WIFI_BIT_DISCONNECTED);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_wifi_reconnect_fail = 0;   /* 拿到 IP 视为连接恢复，清零计数 */
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

/* 读 NVS 凭据；NVS 空则写默认三组（首次启动） */
static void wifi_creds_load(wifi_cred_t *creds, int *out_count)
{
    *out_count = 0;
    nvs_handle_t h;
    if (nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) {
        return;
    }
    uint8_t count = 0;
    if (nvs_get_u8(h, WIFI_NVS_COUNT_KEY, &count) == ESP_ERR_NVS_NOT_FOUND) {
        /* 首次启动：写入默认三组凭据 */
        count = 3;
        nvs_set_u8(h, WIFI_NVS_COUNT_KEY, count);
        for (int i = 0; i < count; i++) {
            char key[16];
            snprintf(key, sizeof(key), WIFI_NVS_ENTRY_KEY, i);
            nvs_set_blob(h, key, &DEFAULT_WIFI_CREDS[i], sizeof(wifi_cred_t));
        }
        nvs_commit(h);
        ESP_LOGI(TAG, "WiFi 凭据首次写入 NVS（%d 组）", count);
    }
    for (int i = 0; i < count && i < MAX_WIFI_CREDS; i++) {
        char key[16];
        snprintf(key, sizeof(key), WIFI_NVS_ENTRY_KEY, i);
        size_t len = sizeof(wifi_cred_t);
        if (nvs_get_blob(h, key, &creds[i], &len) == ESP_OK) {
            (*out_count)++;
        }
    }
    nvs_close(h);
}

/* 扫描匹配：选 prio 最小（最高优先），同 prio 取 RSSI 最强；设置 STA 配置并 connect */
static void wifi_scan_and_connect(void)
{
    wifi_cred_t creds[MAX_WIFI_CREDS];
    int cred_count = 0;
    wifi_creds_load(creds, &cred_count);
    if (cred_count <= 0) {
        ESP_LOGE(TAG, "无 WiFi 凭据，跳过连接");
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
        for (int c = 0; c < cred_count; c++) {
            if (strcmp((char *)aps[i].ssid, creds[c].ssid) == 0) {
                if (creds[c].prio < best_prio ||
                    (creds[c].prio == best_prio && aps[i].rssi > best_rssi)) {
                    best_prio = creds[c].prio;
                    best_rssi = aps[i].rssi;
                    best_cred = c;
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
    strcpy((char *)wc.sta.ssid, creds[best_cred].ssid);
    strcpy((char *)wc.sta.password, creds[best_cred].pass);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;  /* 本次全 WPA2（含 iPhone 热点「最大兼容性」） */
    wc.sta.channel = 0;                               /* 信道不固定，自动全信道扫描 */
    wc.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    wc.sta.pmf_cfg.capable = true;                    /* PMF 可选（802.11w） */
    wc.sta.pmf_cfg.required = false;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_connect());
    free(aps);
}

/* WiFi 管理任务：首次扫描连接 + 断开后重新扫描切换（带指数退避） */
static void wifi_task(void *arg)
{
    wifi_scan_and_connect();
    while (1) {
        xEventGroupWaitBits(s_wifi_events, WIFI_BIT_DISCONNECTED, pdTRUE, pdFALSE, portMAX_DELAY);
        /* 指数退避：连续失败越多等越久（1s 起步，上限 30s），避免信号边缘来回切换 */
        int shift = s_wifi_reconnect_fail < 5 ? s_wifi_reconnect_fail : 5;
        int backoff = 1000 << shift;
        if (backoff > 30000) {
            backoff = 30000;
        }
        ESP_LOGI(TAG, "重新扫描前退避 %d ms", backoff);
        vTaskDelay(pdMS_TO_TICKS(backoff));
        wifi_scan_and_connect();
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

/* ---------------- 播放：跳过 WAV 头，单声道升混立体声（可被按键打断） ---------------- */
static bool play_wav(const uint8_t *wav, int len)
{
    if (len <= WAV_HEADER) {
        return true;
    }
    const int16_t *pcm = (const int16_t *)(wav + WAV_HEADER);
    int n = (len - WAV_HEADER) / 2;   /* 单声道样本数 */
    int idx = 0;
    while (idx < n) {
        if (s_cancel) {
            return false;   /* 按键打断，停止播放 */
        }
        int cnt = n - idx;
        int max_cnt = sizeof(s_stereo) / 4;
        if (cnt > max_cnt) {
            cnt = max_cnt;
        }
        for (int i = 0; i < cnt; i++) {
            s_stereo[i * 2] = pcm[idx + i];
            s_stereo[i * 2 + 1] = pcm[idx + i];
        }
        esp_codec_dev_write(s_spk, (uint8_t *)s_stereo, cnt * 4);
        idx += cnt;
    }
    return true;
}

/* ---------------- 精确读取 n 字节（跨 esp_http_client_read 分片，可被打断） ---------------- */
static bool read_exact(esp_http_client_handle_t client, uint8_t *buf, int n)
{
    int got = 0;
    while (got < n) {
        if (s_cancel) {
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

/* ---------------- 一轮对话：边录边传（chunked 流式）→ 接收播放 ---------------- */
static void voice_round(void)
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
    esp_http_client_set_header(client, "Content-Type", "application/octet-stream");
    esp_http_client_open(client, -1);   /* write_len=-1 → chunked（服务端边收边流式 ASR） */

    /* 2. 边录边传：每读一块 PCM，手动 chunk 编码后 write（esp_http_client 不做自动 chunk 编码） */
    ESP_LOGI(TAG, "REC+UPLOAD START (chunked)");
    int uploaded = 0;
    while (s_recording) {
        int r = esp_codec_dev_read(s_mic, (uint8_t *)s_stereo, sizeof(s_stereo));
        if (r != 0) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        int n_frames = sizeof(s_stereo) / (CHANNELS * 2);
        for (int i = 0; i < n_frames; i++) {
            s_mono[i] = (int16_t)((s_stereo[i * 2] + s_stereo[i * 2 + 1]) / 2);
        }
        int wlen = n_frames * 2;
        /* 手动 chunk 编码：size 十六进制行 + 数据 + CRLF */
        char hdr[16];
        int hlen = snprintf(hdr, sizeof(hdr), "%x\r\n", wlen);
        if (esp_http_client_write(client, hdr, hlen) < 0 ||
            esp_http_client_write(client, (char *)s_mono, wlen) < 0 ||
            esp_http_client_write(client, "\r\n", 2) < 0) {
            ESP_LOGE(TAG, "upload write FAILED");
            break;
        }
        uploaded += wlen;
    }
    /* 结束 chunk（0 长度 chunk = 按键松开的流结束信号） */
    esp_http_client_write(client, "0\r\n\r\n", 5);
    ESP_LOGI(TAG, "REC+UPLOAD END, pcm bytes=%d", uploaded);

    /* 3. 读响应头 */
    esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "HTTP status=%d", status);
    if (status != 200) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return;
    }

    /* 逐帧解析：4 字节大端长度 + WAV 载荷 */
    uint8_t hdr[4];
    int frames = 0;
    while (read_exact(client, hdr, 4)) {
        uint32_t len = ((uint32_t)hdr[0] << 24) | ((uint32_t)hdr[1] << 16) |
                       ((uint32_t)hdr[2] << 8) | (uint32_t)hdr[3];
        if (len == 0 || len > MAX_FRAME) {
            ESP_LOGE(TAG, "bad frame len=%u", (unsigned)len);
            break;
        }
        uint8_t *wav = malloc(len);
        if (!wav) {
            ESP_LOGE(TAG, "frame alloc FAILED (%u)", (unsigned)len);
            break;
        }
        if (!read_exact(client, wav, (int)len)) {
            free(wav);
            break;
        }
        if (!play_wav(wav, (int)len)) {
            free(wav);
            break;   /* 按键打断 */
        }
        free(wav);
        frames++;
    }
    ESP_LOGI(TAG, "PLAY DONE, frames=%d%s", frames, s_cancel ? " (cancelled)" : "");

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

/* ---------------- 对话任务：录音上传 + 收帧播放（可被按键打断） ---------------- */
static void talk_task(void *arg)
{
    while (true) {
        while (!s_recording) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
        s_cancel = false;   /* 清除打断标志，开始新对话 */
        ESP_LOGI(TAG, ">> TALK START");
        voice_round();
        ESP_LOGI(TAG, "<< TALK DONE");
        if (!s_recording) {
            /* 正常结束：松开后防抖 */
            vTaskDelay(pdMS_TO_TICKS(200));
        }
        /* 若被打断（s_recording 仍 true，用户还按着），立即循环开始新录音，不丢语音 */
    }
}

/* ---------------- 主入口 ---------------- */
void app_main(void)
{
    ESP_LOGI(TAG, "=== voice_agent boot (v0.4) ===");

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

    /* WiFi：初始化 + 管理任务（扫描连接 + 断开重连切换），等首次拿到 IP 再进入交互 */
    s_wifi_events = xEventGroupCreate();
    wifi_init();
    xTaskCreate(wifi_task, "wifi", 4096, NULL, 5, NULL);
    xEventGroupWaitBits(s_wifi_events, WIFI_BIT_CONNECTED, pdFALSE, pdFALSE, pdMS_TO_TICKS(30000));

    /* 按键：按住说话（顶部圆键=GPIO1=MUTE，Boot键=GPIO0=CONFIG 双注册） */
    bsp_btn_init();
    bsp_btn_register_callback(BSP_BUTTON_MUTE, BUTTON_PRESS_DOWN, talk_btn_cb, NULL);
    bsp_btn_register_callback(BSP_BUTTON_MUTE, BUTTON_PRESS_UP, talk_btn_cb, NULL);
    bsp_btn_register_callback(BSP_BUTTON_CONFIG, BUTTON_PRESS_DOWN, talk_btn_cb, NULL);
    bsp_btn_register_callback(BSP_BUTTON_CONFIG, BUTTON_PRESS_UP, talk_btn_cb, NULL);
    ESP_LOGI(TAG, "push-to-talk ready: hold TOP button to speak");

    /* 对话任务：独立任务跑 talk_task，播放可被按键打断（app_main 主任务返回） */
    xTaskCreate(talk_task, "talk", 8192, NULL, 5, NULL);
}
