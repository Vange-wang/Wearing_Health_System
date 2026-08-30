/*
 * SPDX-License-Identifier: CC0-1.0
 *
 * ble_central — P2/P3 BOX-3 BLE central（zcode, 2026-08-23）
 *
 * 功能（任务单 2026-08-23-P2/P3-BOX3-BLEcentral）：
 *   1. 扫描匹配腕部节点 WH-Wrist01（名字前缀 WH- + 厂商段 0xFFFF 能力位 bit0/bit1）
 *   2. 连接 → 服务发现（combo 0x7a0b1000…）→ 订阅综合帧特征 notify（0x7a0b1001…）
 *   3. 8 字节帧解析缓存（seq 丢帧检测 / HR-uint16LE / SpO2 / conf / flags / battery）
 *   4. NVS 存对端 MAC → 开机直连 + 断线后台重连（指数退避，不阻塞语音任务）
 *   5. P3：有效帧经 HTTP POST 上报 voice-bridge /api/v1/health/data（独立后台任务）
 * 首字红线：本模块全部在 NimBLE 主机任务 / 独立重连 / 独立上报任务，不进入语音首字路径。
 *
 * API 注意（IDF v5.2.7 内置 NimBLE）：
 *   - GATT 客户端发现用独立回调（ble_gatt_disc_svc_fn / chr_fn / dsc_fn），
 *     完成标志 error->status == BLE_HS_EDONE；不是 GAP 事件
 *   - ble_gap_disc 需 struct ble_gap_disc_params（filter_policy 用 BLE_HCI_SCAN_FILT_NO_WL）
 *   - notify 接收事件为 BLE_GAP_EVENT_NOTIFY_RX
 */
#include "ble_central.h"
#include <string.h>
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "device_auth_client.h"

static const char *TAG = "ble_central";

/* ---- P3 上报（任务单 2026-08-23-P3）：与 HEALTH_URL 同域，mDNS 由 voice_agent 初始化 ---- */
#define HEALTH_DATA_URL "http://voicebridge.local:8710/api/v1/health/data"
#define UPLOAD_RETRY_MS 2000   /* 失败重试 1 次间隔 */

/* ---- 目标匹配（与 P1 ble_periph.c 对齐，改动需两端同步） ---- */
#define TARGET_NAME_PREFIX "WH-"
#define TARGET_MFG_COMPANY  0xFFFF   /* mfg_data[0:1] LE */
#define TARGET_MFG_CAPS     0x03     /* mfg_data[2]: bit0 心率 bit1 血氧 */

static const ble_uuid128_t svc_combo_uuid = BLE_UUID128_INIT(
    0x0b, 0x9a, 0x8f, 0x7e, 0x6d, 0x5c, 0x3b, 0x9a,
    0x2f, 0x4e, 0x1d, 0x8c, 0x00, 0x10, 0x0b, 0x7a);   /* 7a0b1000-… */
static const ble_uuid128_t chr_combo_uuid = BLE_UUID128_INIT(
    0x0b, 0x9a, 0x8f, 0x7e, 0x6d, 0x5c, 0x3b, 0x9a,
    0x2f, 0x4e, 0x1d, 0x8c, 0x01, 0x10, 0x0b, 0x7a);   /* 7a0b1001-… */
static const ble_uuid16_t  dsc_cccd_uuid  = BLE_UUID16_INIT(0x2902);

/* ---- 连接参数（任务单契约：100~200ms 间隔 / latency 4 / 超时 4s） ---- */
static const struct ble_gap_conn_params s_conn_params = {
    .scan_itvl = 0x0010,
    .scan_window = 0x0010,
    .itvl_min = 80,                /* 100ms */
    .itvl_max = 160,               /* 200ms */
    .latency = 4,
    .supervision_timeout = 400,    /* 4s */
    .min_ce_len = 0,
    .max_ce_len = 0,
};

/* ---- 扫描参数 ---- */
#define SCAN_DURATION_MS 10000
static const struct ble_gap_disc_params s_disc_params = {
    .itvl = 0x0010,                    /* 10ms */
    .window = 0x0010,
    .filter_policy = BLE_HCI_SCAN_FILT_NO_WL,
    .limited = 0,
    .passive = 0,
    .filter_duplicates = 0,
    .disable_observer_mode = 0,
};

/* ---- NVS ---- */
#define NVS_NS      "ble_cfg"
#define NVS_KEY_ADDR "peer_addr"
#define NVS_KEY_MAC_LEGACY "peer_mac"

/* ---- 状态 ---- */
static volatile bool s_connected = false;
static volatile bool s_scanning = false;
static uint16_t s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static uint16_t s_combo_svc_end_handle = 0;
static uint16_t s_combo_val_handle = 0;
static uint16_t s_combo_cccd_handle = 0;
static bool s_notify_subscribed = false;

static ble_addr_t s_peer_addr;
static bool s_peer_addr_valid = false;

/* 缓存（临界区保护，语音任务可随时读） */
static portMUX_TYPE s_cache_mux = portMUX_INITIALIZER_UNLOCKED;
static ble_health_t s_health = { 0 };

/* 重连触发信号量：开机直连 / 断线 / 连接失败时 give */
static SemaphoreHandle_t s_reconnect_sem = NULL;
/* 上报触发信号量：cache_frame 收到有效帧时 give，上传任务消费 */
static SemaphoreHandle_t s_upload_sem = NULL;

static int gap_event_cb(struct ble_gap_event *event, void *arg);
static int disc_chr_cb(uint16_t conn_handle, const struct ble_gatt_error *error,
                       const struct ble_gatt_chr *chr, void *arg);

/* ---------------- NVS ---------------- */
typedef struct {
    uint8_t type;
    uint8_t val[6];
} peer_addr_record_t;

static peer_addr_record_t peer_record_from_addr(const ble_addr_t *addr)
{
    peer_addr_record_t record = { .type = addr->type };
    memcpy(record.val, addr->val, sizeof(record.val));
    return record;
}

static bool peer_addr_from_record(const peer_addr_record_t *record,
                                  ble_addr_t *addr)
{
    if (record->type > BLE_ADDR_RANDOM_ID) {
        return false;
    }
    addr->type = record->type;
    memcpy(addr->val, record->val, sizeof(record->val));
    return true;
}

static bool nvs_store_addr(const ble_addr_t *addr)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) {
        return false;
    }
    peer_addr_record_t record = peer_record_from_addr(addr);
    esp_err_t err = nvs_set_blob(h, NVS_KEY_ADDR, &record, sizeof(record));
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "对端地址写入 NVS 失败: %s", esp_err_to_name(err));
        return false;
    }
    ESP_LOGI(TAG,
             "对端地址已存 NVS type=%u %02x:%02x:%02x:%02x:%02x:%02x",
             addr->type, addr->val[0], addr->val[1], addr->val[2],
             addr->val[3], addr->val[4], addr->val[5]);
    return true;
}

static bool nvs_load_addr(ble_addr_t *addr)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        return false;
    }
    peer_addr_record_t record = {0};
    size_t len = sizeof(record);
    bool ok = (nvs_get_blob(h, NVS_KEY_ADDR, &record, &len) == ESP_OK &&
               len == sizeof(record));
    bool migrated_legacy = false;
    if (!ok) {
        len = sizeof(record.val);
        if (nvs_get_blob(h, NVS_KEY_MAC_LEGACY, record.val, &len) == ESP_OK &&
            len == sizeof(record.val)) {
            record.type = BLE_ADDR_PUBLIC;
            ok = true;
            migrated_legacy = true;
        }
    }
    nvs_close(h);
    if (ok) {
        ok = peer_addr_from_record(&record, addr);
        if (migrated_legacy) {
            (void)nvs_store_addr(addr);
        }
    }
    return ok;
}

/* ---------------- 帧解析缓存 ---------------- */
static void invalidate_health(ble_health_t *health)
{
    uint32_t lost = health->lost;
    memset(health, 0, sizeof(*health));
    health->lost = lost;
}

static void invalidate_cache(void)
{
    portENTER_CRITICAL(&s_cache_mux);
    invalidate_health(&s_health);
    portEXIT_CRITICAL(&s_cache_mux);
}

static void apply_frame(ble_health_t *health, const uint8_t frame[8],
                        uint32_t ts_ms)
{
    ble_health_t h = {0};
    h.seq = frame[0];
    h.flags = frame[1];
    h.hr = (uint16_t)frame[2] | ((uint16_t)frame[3] << 8);
    h.spo2 = frame[4];
    h.conf = frame[5];
    h.battery = frame[6];
    h.ts_ms = ts_ms;
    if (health->valid) {
        /* 丢帧检测：seq 递增（8-bit 回绕），差值 >1 计丢帧 */
        uint8_t diff = (uint8_t)(h.seq - health->seq);
        if (diff > 1) {
            health->lost += (uint32_t)(diff - 1);
        }
    }
    h.lost = health->lost;
    h.valid = true;
    *health = h;
}

static void cache_frame(const uint8_t frame[8])
{
    ble_health_t h;
    portENTER_CRITICAL(&s_cache_mux);
    apply_frame(&s_health, frame,
                (uint32_t)(esp_timer_get_time() / 1000));
    h = s_health;
    portEXIT_CRITICAL(&s_cache_mux);

    ESP_LOGI(TAG, "帧 seq=%u HR=%u SpO2=%u conf=%u flags=0x%02x bat=%u lost=%lu",
             h.seq, h.hr, h.spo2, h.conf, h.flags, h.battery,
             (unsigned long)h.lost);

    /* 每帧均上报链路/质量状态；无有效生理字段时服务端只刷新 link_ts。 */
    if (s_upload_sem) {
        xSemaphoreGive(s_upload_sem);
    }
}

/* ---------------- GATT 客户端回调（独立于 GAP 事件） ---------------- */

static int cccd_write_cb(uint16_t conn_handle,
                         const struct ble_gatt_error *error,
                         struct ble_gatt_attr *attr, void *arg)
{
    (void)arg;
    uint16_t attr_handle = attr != NULL ? attr->handle : s_combo_cccd_handle;
    if (error->status == 0) {
        s_notify_subscribed = true;
        ESP_LOGI(TAG, "CCCD 写入完成 conn=%u handle=0x%04x",
                 conn_handle, attr_handle);
    } else {
        s_notify_subscribed = false;
        ESP_LOGW(TAG, "CCCD 写入失败 status=%d conn=%u handle=0x%04x",
                 error->status, conn_handle, attr_handle);
    }
    return 0;
}

/* 特征发现完成 → 找到 CCCD 并订阅 notify */
static int disc_dsc_cb(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       uint16_t chr_val_handle,
                       const struct ble_gatt_dsc *dsc, void *arg)
{
    (void)chr_val_handle;
    (void)arg;
    if (error->status == 0 && dsc != NULL &&
        ble_uuid_cmp(&dsc->uuid.u, &dsc_cccd_uuid.u) == 0) {
        s_combo_cccd_handle = dsc->handle;
        uint8_t cccd_val[2] = {0x01, 0x00};
        int rc = ble_gattc_write_flat(conn_handle, dsc->handle,
                                      cccd_val, sizeof(cccd_val), cccd_write_cb,
                                      NULL);
        ESP_LOGI(TAG, "订阅 notify cccd=0x%04x rc=%d", dsc->handle, rc);
    } else if (error->status == BLE_HS_EDONE && s_combo_cccd_handle == 0) {
        ESP_LOGW(TAG, "未找到 CCCD（val_handle=0x%04x）", s_combo_val_handle);
    }
    return 0;
}

/* 服务发现完成 → 发起特征发现 */
static int disc_svc_cb(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_svc *service, void *arg)
{
    (void)arg;
    if (error->status == 0 && service != NULL &&
        ble_uuid_cmp(&service->uuid.u, &svc_combo_uuid.u) == 0) {
        ESP_LOGI(TAG, "找到综合帧服务 start=0x%04x end=0x%04x",
                 service->start_handle, service->end_handle);
        s_combo_svc_end_handle = service->end_handle;
        int rc = ble_gattc_disc_chrs_by_uuid(conn_handle,
                                             service->start_handle,
                                             service->end_handle,
                                             &chr_combo_uuid.u,
                                             disc_chr_cb, NULL);
        if (rc != 0) {
            ESP_LOGW(TAG, "特征发现发起失败 rc=%d", rc);
        }
    }
    return 0;
}

/* 特征发现完成 → 记录 val_handle → 发现 CCCD 描述符 */
static int disc_chr_cb(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_chr *chr, void *arg)
{
    (void)arg;
    if (error->status == 0 && chr != NULL &&
        ble_uuid_cmp(&chr->uuid.u, &chr_combo_uuid.u) == 0) {
        s_combo_val_handle = chr->val_handle;
        ESP_LOGI(TAG, "找到综合帧特征 val_handle=0x%04x", s_combo_val_handle);
        int rc = ble_gattc_disc_all_dscs(conn_handle, chr->val_handle,
                                         s_combo_svc_end_handle,
                                         disc_dsc_cb, NULL);
        if (rc != 0) {
            ESP_LOGW(TAG, "描述符发现发起失败 rc=%d", rc);
        }
    }
    return 0;
}

/* ---------------- GAP 事件 ---------------- */
static bool required_caps_present(uint8_t capabilities)
{
    return (capabilities & TARGET_MFG_CAPS) == TARGET_MFG_CAPS;
}

static void start_connect(const ble_addr_t *addr)
{
    int rc = ble_gap_connect(BLE_OWN_ADDR_PUBLIC, addr, SCAN_DURATION_MS,
                             &s_conn_params, gap_event_cb, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGW(TAG, "connect 发起失败 rc=%d", rc);
    }
}

static int start_scan(void)
{
    if (s_scanning) {
        return 0;
    }
    s_scanning = true;
    int rc = ble_gap_disc(BLE_OWN_ADDR_PUBLIC, SCAN_DURATION_MS,
                          &s_disc_params, gap_event_cb, NULL);
    if (rc != 0) {
        s_scanning = false;
        ESP_LOGW(TAG, "扫描发起失败 rc=%d", rc);
        return rc;
    }
    ESP_LOGI(TAG, "开始扫描（%d ms）", SCAN_DURATION_MS);
    return 0;
}

static int gap_event_cb(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    switch (event->type) {

    /* ---- 扫描结果 ---- */
    case BLE_GAP_EVENT_DISC: {
        struct ble_hs_adv_fields fields;
        if (ble_hs_adv_parse_fields(&fields, event->disc.data,
                                    event->disc.length_data) != 0) {
            return 0;
        }
        bool name_ok = (fields.name != NULL && fields.name_len >= 3 &&
                        memcmp(fields.name, TARGET_NAME_PREFIX, 3) == 0);
        bool mfg_ok = (fields.mfg_data != NULL && fields.mfg_data_len >= 3 &&
                       fields.mfg_data[0] == (TARGET_MFG_COMPANY & 0xFF) &&
                       fields.mfg_data[1] == ((TARGET_MFG_COMPANY >> 8) & 0xFF) &&
                       required_caps_present(fields.mfg_data[2]));
        if (name_ok && mfg_ok) {
            ESP_LOGI(TAG, "命中腕部节点 %02x:%02x:%02x:%02x:%02x:%02x rssi=%d",
                     event->disc.addr.val[0], event->disc.addr.val[1],
                     event->disc.addr.val[2], event->disc.addr.val[3],
                     event->disc.addr.val[4], event->disc.addr.val[5],
                     event->disc.rssi);
            ble_gap_disc_cancel();
            s_scanning = false;
            s_peer_addr = event->disc.addr;
            s_peer_addr_valid = true;
            (void)nvs_store_addr(&s_peer_addr);
            start_connect(&event->disc.addr);
        }
        return 0;
    }

    case BLE_GAP_EVENT_DISC_COMPLETE:
        s_scanning = false;
        ESP_LOGI(TAG, "扫描结束 reason=%d", event->disc_complete.reason);
        return 0;

    /* ---- 连接结果 ---- */
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_conn_handle = event->connect.conn_handle;
            s_connected = true;
            s_combo_svc_end_handle = 0;
            s_combo_val_handle = 0;
            s_combo_cccd_handle = 0;
            s_notify_subscribed = false;
            ESP_LOGI(TAG, "已连接 conn=%d，开始服务发现", s_conn_handle);
            int rc = ble_gattc_disc_svc_by_uuid(s_conn_handle,
                                                &svc_combo_uuid.u,
                                                disc_svc_cb, NULL);
            if (rc != 0) {
                ESP_LOGW(TAG, "服务发现发起失败 rc=%d", rc);
            }
        } else {
            ESP_LOGW(TAG, "连接失败 rc=%d，调度重连", event->connect.status);
            s_connected = false;
            s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            if (s_reconnect_sem) {
                xSemaphoreGive(s_reconnect_sem);
            }
        }
        return 0;

    /* ---- notify 数据（IDF NimBLE 事件名 NOTIFY_RX） ---- */
    case BLE_GAP_EVENT_NOTIFY_RX:
        if (event->notify_rx.attr_handle == s_combo_val_handle) {
            uint8_t frame[8];
            int rc = os_mbuf_copydata(event->notify_rx.om, 0,
                                      sizeof(frame), frame);
            if (rc == 0) {
                cache_frame(frame);
            }
        }
        return 0;

    /* ---- 断开 ---- */
    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGW(TAG, "连接断开 reason=%d，调度后台重连", event->disconnect.reason);
        s_connected = false;
        s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
        s_combo_svc_end_handle = 0;
        s_combo_val_handle = 0;
        s_combo_cccd_handle = 0;
        s_notify_subscribed = false;
        invalidate_cache();
        if (s_reconnect_sem) {
            xSemaphoreGive(s_reconnect_sem);
        }
        return 0;

    default:
        return 0;
    }
}

/* ---------------- 后台重连任务（不阻塞语音） ---------------- */
static void reconnect_task(void *arg)
{
    (void)arg;
    int retry = 0;
    while (1) {
        /* 等触发：开机直连 / 断开 / 连接失败 */
        xSemaphoreTake(s_reconnect_sem, portMAX_DELAY);

        while (!s_connected) {
            if (s_peer_addr_valid) {
                start_connect(&s_peer_addr);
            } else {
                start_scan();
            }
            /* 等连接结果（最多 12s，含扫描 10s + 连接握手余量） */
            for (int i = 0; i < 24 && !s_connected; i++) {
                vTaskDelay(pdMS_TO_TICKS(500));
            }
            if (s_connected) {
                retry = 0;
                break;
            }
            /* 指数退避：2s/4s/8s/…/封顶 30s */
            retry++;
            int shift = retry < 5 ? (retry - 1) : 4;
            int backoff = 2000 << shift;
            if (backoff > 30000) {
                backoff = 30000;
            }
            ESP_LOGI(TAG, "重连（第 %d 次，退避 %d ms）", retry, backoff);
            vTaskDelay(pdMS_TO_TICKS(backoff));
        }
        retry = 0;
    }
}

/* ---------------- P3 上报任务（独立后台，不阻塞 BLE 收帧/语音） ---------------- */

static bool http_post_health(const ble_health_t *h)
{
    /* 无效字段传 null（服务端 Pydantic 可空；None 不覆盖值） */
    char body[160];
    double quality = (double)(h->conf > 100 ? 100 : h->conf) / 100.0;
    if ((h->flags & 0x01) && (h->flags & 0x02)) {
        snprintf(body, sizeof(body),
                 "{\"hr\":%u,\"spo2\":%u,\"seq\":%u,\"flags\":%u,\"quality\":%.2f}",
                 h->hr, h->spo2, h->seq, h->flags, quality);
    } else if (h->flags & 0x01) {
        snprintf(body, sizeof(body),
                 "{\"hr\":%u,\"spo2\":null,\"seq\":%u,\"flags\":%u,\"quality\":%.2f}",
                 h->hr, h->seq, h->flags, quality);
    } else if (h->flags & 0x02) {
        snprintf(body, sizeof(body),
                 "{\"hr\":null,\"spo2\":%u,\"seq\":%u,\"flags\":%u,\"quality\":%.2f}",
                 h->spo2, h->seq, h->flags, quality);
    } else {
        snprintf(body, sizeof(body),
                 "{\"hr\":null,\"spo2\":null,\"seq\":%u,\"flags\":%u,\"quality\":%.2f}",
                 h->seq, h->flags, quality);
    }

    esp_http_client_config_t cfg = {
        .url = HEALTH_DATA_URL,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 5000,
        .buffer_size = 512,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        return false;
    }
    esp_http_client_set_header(client, "Content-Type", "application/json");

    bool ok = false;
    int wlen = (int)strlen(body);
    if (open_authenticated_http(client, wlen) == ESP_OK &&
        esp_http_client_write(client, body, wlen) >= 0 &&
        esp_http_client_fetch_headers(client) >= 0 &&
        esp_http_client_get_status_code(client) == 200) {
        ok = true;
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return ok;
}

static void upload_task(void *arg)
{
    (void)arg;
    int fail_streak = 0;
    bool first_upload_done = false;
    while (1) {
        xSemaphoreTake(s_upload_sem, portMAX_DELAY);
        ble_health_t h;
        if (!ble_central_get_data(&h)) {
            continue;
        }
        bool ok = false;
        for (int attempt = 0; attempt < 2 && !ok; attempt++) {   /* 首次 + 重试 1 次 */
            ok = http_post_health(&h);
            if (!ok && attempt == 0) {
                vTaskDelay(pdMS_TO_TICKS(UPLOAD_RETRY_MS));
            }
        }
        if (ok) {
            if (fail_streak > 0 || !first_upload_done) {
                ESP_LOGI(TAG, "上报成功 hr=%u spo2=%u seq=%u", h.hr, h.spo2, h.seq);
                first_upload_done = true;
            }
            fail_streak = 0;
        } else {
            fail_streak++;
            /* 静默降噪：仅首次失败与每 12 次连续失败打一条 */
            if (fail_streak == 1 || fail_streak % 12 == 0) {
                ESP_LOGW(TAG, "上报失败（连续 %d 次，网络/服务端未就绪？）", fail_streak);
            }
        }
    }
}

/* ---------------- NimBLE host ---------------- */
static void on_sync(void)
{
    ESP_LOGI(TAG, "NimBLE 主机同步完成");
    if (s_peer_addr_valid) {
        ESP_LOGI(TAG, "已存对端地址，尝试开机直连");
        if (s_reconnect_sem) {
            xSemaphoreGive(s_reconnect_sem);
        }
    } else {
        ESP_LOGI(TAG, "无对端 MAC（首次配对），等待按键触发扫描");
    }
}

static void nimble_host_task(void *param)
{
    (void)param;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

#ifdef BLE_CENTRAL_SELF_TEST
static esp_err_t ble_central_state_selftest(void)
{
    const uint8_t cccd_val[2] = {0x01, 0x00};
    if (cccd_val[0] != 1 || cccd_val[1] != 0 ||
        required_caps_present(0x01) || required_caps_present(0x02) ||
        !required_caps_present(0x03)) {
        return ESP_FAIL;
    }

    ble_addr_t random_addr = { .type = BLE_ADDR_RANDOM };
    const uint8_t expected_addr[6] = {1, 2, 3, 4, 5, 6};
    memcpy(random_addr.val, expected_addr, sizeof(expected_addr));
    peer_addr_record_t record = peer_record_from_addr(&random_addr);
    ble_addr_t decoded_addr = {0};
    if (!peer_addr_from_record(&record, &decoded_addr) ||
        decoded_addr.type != BLE_ADDR_RANDOM ||
        memcmp(decoded_addr.val, expected_addr, sizeof(expected_addr)) != 0) {
        return ESP_FAIL;
    }

    ble_health_t health = {0};
    const uint8_t frame_a[8] = {250, 0x03, 75, 0, 98, 80, 100, 0};
    const uint8_t frame_b[8] = {253, 0x03, 76, 0, 98, 80, 100, 0};
    const uint8_t frame_c[8] = {100, 0x05, 75, 0, 0, 40, 100, 0};
    apply_frame(&health, frame_a, 1000);
    apply_frame(&health, frame_b, 2000);
    if (!health.valid || health.lost != 2 || health.flags != 0x03) {
        return ESP_FAIL;
    }
    invalidate_health(&health);
    if (health.valid || health.lost != 2) {
        return ESP_FAIL;
    }
    apply_frame(&health, frame_c, 3000);
    if (!health.valid || health.seq != 100 || health.lost != 2 ||
        health.flags != 0x05 || health.conf != 40) {
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "BLE central state self-test PASS");
    return ESP_OK;
}
#endif

/* ---------------- 对外 API ---------------- */
esp_err_t ble_central_init(void)
{
#ifdef BLE_CENTRAL_SELF_TEST
    esp_err_t selftest_err = ble_central_state_selftest();
    if (selftest_err != ESP_OK) {
        return selftest_err;
    }
#endif
    s_peer_addr_valid = nvs_load_addr(&s_peer_addr);
    if (s_peer_addr_valid) {
        ESP_LOGI(TAG,
                 "NVS 读取对端地址 type=%u %02x:%02x:%02x:%02x:%02x:%02x",
                 s_peer_addr.type, s_peer_addr.val[0], s_peer_addr.val[1],
                 s_peer_addr.val[2], s_peer_addr.val[3], s_peer_addr.val[4],
                 s_peer_addr.val[5]);
    }

    s_reconnect_sem = xSemaphoreCreateBinary();
    if (!s_reconnect_sem) {
        return ESP_ERR_NO_MEM;
    }
    s_upload_sem = xSemaphoreCreateBinary();
    if (!s_upload_sem) {
        return ESP_ERR_NO_MEM;
    }

    ble_hs_cfg.reset_cb = NULL;
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_hs_cfg.gatts_register_cb = NULL;

    nimble_port_init();

    BaseType_t reconnect_task_result = xTaskCreate(
        reconnect_task, "ble_reconn", 4096, NULL, 4, NULL);
    if (reconnect_task_result != pdPASS) {
        ESP_LOGE(TAG, "reconnect task create FAILED rc=%ld",
                 (long)reconnect_task_result);
        return ESP_ERR_NO_MEM;
    }

    BaseType_t upload_task_result = xTaskCreateWithCaps(
        upload_task, "ble_upload", 4096, NULL, 4, NULL,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (upload_task_result != pdPASS) {
        ESP_LOGE(TAG, "upload task create FAILED rc=%ld",
                 (long)upload_task_result);
        return ESP_ERR_NO_MEM;
    }

    nimble_port_freertos_init(nimble_host_task);
    ESP_LOGI(TAG, "BLE central 就绪（目标 WH-* / 能力位 0x%02x）", TARGET_MFG_CAPS);
    return ESP_OK;
}

void ble_central_start_scan(void)
{
    if (s_connected) {
        ESP_LOGI(TAG, "已连接，忽略扫描请求");
        return;
    }
    if (s_scanning) {
        ESP_LOGI(TAG, "已在扫描中");
        return;
    }
    if (start_scan() != 0) {
        /* NimBLE 可能未就绪（EBUSY）：交给重连任务延迟重试 */
        if (s_reconnect_sem) {
            xSemaphoreGive(s_reconnect_sem);
        }
    }
}

bool ble_central_is_connected(void)
{
    return s_connected;
}

bool ble_central_get_data(ble_health_t *out)
{
    if (out == NULL) {
        return false;
    }
    portENTER_CRITICAL(&s_cache_mux);
    bool ok = s_health.valid;
    if (ok) {
        *out = s_health;
    }
    portEXIT_CRITICAL(&s_cache_mux);
    return ok;
}
