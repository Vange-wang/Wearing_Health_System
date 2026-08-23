#include "ble_periph.h"
#include <string.h>
#include "esp_log.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"

static const char *TAG = "ble";

#define DEVICE_NAME "WH-Wrist01"
#define MANUF_NAME  "WearableHealth/1.0"

/* UUID（与 2026-08-19-BLE数据帧协议 对齐，改动需两端同步） */
static const ble_uuid16_t svc_hr_uuid    = BLE_UUID16_INIT(0x180D);
static const ble_uuid16_t chr_hr_uuid    = BLE_UUID16_INIT(0x2A37);
static const ble_uuid16_t chr_bsl_uuid   = BLE_UUID16_INIT(0x2A38);
static const ble_uuid16_t svc_dis_uuid   = BLE_UUID16_INIT(0x180A);
static const ble_uuid16_t chr_mfg_uuid   = BLE_UUID16_INIT(0x2A29);
static const ble_uuid128_t svc_combo_uuid = BLE_UUID128_INIT(0x0b, 0x9a, 0x8f, 0x7e, 0x6d, 0x5c, 0x3b, 0x9a, 0x2f, 0x4e, 0x1d, 0x8c, 0x00, 0x10, 0x0b, 0x7a);
static const ble_uuid128_t chr_combo_uuid = BLE_UUID128_INIT(0x0b, 0x9a, 0x8f, 0x7e, 0x6d, 0x5c, 0x3b, 0x9a, 0x2f, 0x4e, 0x1d, 0x8c, 0x01, 0x10, 0x0b, 0x7a);

static uint16_t hr_val_handle;
static uint16_t combo_val_handle;
static uint16_t conn_handle = BLE_HS_CONN_HANDLE_NONE;

/* 0x2A37 当前测量值：flags(0=8bit BPM) + BPM */
static uint8_t hr_meas[2] = { 0x00, 0x00 };
/* 0x2A38 Body Sensor Location：0x03 = Finger（P1 指尖式） */
static const uint8_t body_location = 0x03;
/* 0x2A29 厂商名 */
static const char mfg_name[] = MANUF_NAME;

static int hr_access_cb(uint16_t conn, uint16_t attr_handle,
                        struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    int rc = os_mbuf_append(ctxt->om, hr_meas, sizeof(hr_meas));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int bsl_access_cb(uint16_t conn, uint16_t attr_handle,
                         struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    int rc = os_mbuf_append(ctxt->om, &body_location, sizeof(body_location));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static int mfg_access_cb(uint16_t conn, uint16_t attr_handle,
                         struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    const char *name = (arg != NULL) ? (const char *)arg : (const char *)mfg_name;
    int rc = os_mbuf_append(ctxt->om, name, strlen(name));
    return rc == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

/* notify-only 特征占位回调（NimBLE 要求 access_cb 非空） */
static int notify_only_cb(uint16_t conn, uint16_t attr_handle,
                          struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    return 0;
}

static const struct ble_gatt_chr_def hr_chrs[] = {
    {
        .uuid = &chr_hr_uuid.u,
        .access_cb = hr_access_cb,
        .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
        .val_handle = &hr_val_handle,
    },
    {
        .uuid = &chr_bsl_uuid.u,
        .access_cb = bsl_access_cb,
        .flags = BLE_GATT_CHR_F_READ,
    },
    { 0 }
};

static const struct ble_gatt_chr_def combo_chrs[] = {
    {
        .uuid = &chr_combo_uuid.u,
        .access_cb = notify_only_cb,
        .flags = BLE_GATT_CHR_F_NOTIFY,
        .val_handle = &combo_val_handle,
    },
    { 0 }
};

static const struct ble_gatt_chr_def dis_chrs[] = {
    {
        .uuid = &chr_mfg_uuid.u,
        .access_cb = mfg_access_cb,
        .flags = BLE_GATT_CHR_F_READ,
        .arg = (void *)mfg_name,
    },
    { 0 }
};

static const struct ble_gatt_svc_def gatt_svcs[] = {
    { .type = BLE_GATT_SVC_TYPE_PRIMARY, .uuid = &svc_hr_uuid.u, .characteristics = hr_chrs },
    { .type = BLE_GATT_SVC_TYPE_PRIMARY, .uuid = &svc_combo_uuid.u, .characteristics = combo_chrs },
    { .type = BLE_GATT_SVC_TYPE_PRIMARY, .uuid = &svc_dis_uuid.u, .characteristics = dis_chrs },
    { 0 }
};

/* 广播：厂商段 0xFFFF + 能力位 0x0003（bit0 心率 bit1 血氧） */
static const uint8_t mfg_adv[] = { 0xFF, 0xFF, 0x03, 0x00 };

static const struct ble_hs_adv_fields adv_fields = {
    .flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP,
    .mfg_data = mfg_adv,
    .mfg_data_len = sizeof(mfg_adv),
    .name = (const uint8_t *)DEVICE_NAME,
    .name_len = sizeof(DEVICE_NAME) - 1,
    .name_is_complete = 1,
};

static struct ble_gap_adv_params adv_params = {
    .conn_mode = BLE_GAP_CONN_MODE_UND,
    .disc_mode = BLE_GAP_DISC_MODE_GEN,
    .itvl_min = 0x30,   /* 30ms */
    .itvl_max = 0x60,   /* 60ms */
};

static int gap_event_cb(struct ble_gap_event *event, void *arg);

static void start_advertising(void)
{
    int rc = ble_gap_adv_set_fields(&adv_fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_set_fields 失败 rc=%d", rc);
        return;
    }
    rc = ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                           &adv_params, gap_event_cb, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_start 失败 rc=%d", rc);
    }
}

static int gap_event_cb(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            conn_handle = event->connect.conn_handle;
            ESP_LOGI(TAG, "连接建立 conn=%d", conn_handle);
            /* 连接参数：100~200ms 间隔，latency 4，超时 4s */
            struct ble_gap_upd_params upd = {
                .itvl_min = 160,
                .itvl_max = 320,
                .latency = 4,
                .supervision_timeout = 400,
                .min_ce_len = 0,
                .max_ce_len = 0,
            };
            ble_gap_update_params(conn_handle, &upd);
        }
        return 0;

    case BLE_GAP_EVENT_DISCONNECT:
        ESP_LOGI(TAG, "断开 reason=%d，恢复广播", event->disconnect.reason);
        conn_handle = BLE_HS_CONN_HANDLE_NONE;
        start_advertising();
        return 0;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        start_advertising();
        return 0;

    default:
        return 0;
    }
}

static void on_sync(void)
{
    ESP_LOGI(TAG, "主机同步，开始广播");
    start_advertising();
}

/* NimBLE 主机任务函数（esp_nimble_enable 直接用它建任务，不能为 NULL） */
static void nimble_host_task(void *param)
{
    ESP_LOGI(TAG, "NimBLE 主机任务启动");
    nimble_port_run();
    nimble_port_freertos_deinit();
}

esp_err_t ble_periph_init(void)
{
    ble_hs_cfg.reset_cb = NULL;
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_hs_cfg.gatts_register_cb = NULL;

    nimble_port_init();

    ble_svc_gap_init();
    ble_svc_gatt_init();

    int rc = ble_gatts_count_cfg(gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "gatts_count_cfg 失败 rc=%d", rc);
        return ESP_FAIL;
    }
    rc = ble_gatts_add_svcs(gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "gatts_add_svcs 失败 rc=%d", rc);
        return ESP_FAIL;
    }

    ble_svc_gap_device_name_set(DEVICE_NAME);

    nimble_port_freertos_init(nimble_host_task);
    ESP_LOGI(TAG, "peripheral 就绪（%s，Just Works 不加密，不绑定）", DEVICE_NAME);
    return ESP_OK;
}

bool ble_is_connected(void)
{
    return conn_handle != BLE_HS_CONN_HANDLE_NONE;
}

void ble_notify_frame(const uint8_t frame[8], uint8_t hr_bpm)
{
    if (conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        return;
    }

    /* 自定义综合帧（主通道） */
    struct os_mbuf *om = ble_hs_mbuf_from_flat(frame, 8);
    if (om != NULL) {
        ble_gatts_notify_custom(conn_handle, combo_val_handle, om);
    }

    /* 标准心率特征 0x2A37：flags + 8bit BPM */
    hr_meas[1] = hr_bpm;
    om = ble_hs_mbuf_from_flat(hr_meas, sizeof(hr_meas));
    if (om != NULL) {
        ble_gatts_notify_custom(conn_handle, hr_val_handle, om);
    }
}
