
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#define TARGET_MFG_CAPS 3
#define TARGET_MFG_COMPANY 65535
#define TARGET_NAME_PREFIX "WH-"
#define SCAN_DURATION_MS 10000
#define BLE_OWN_ADDR_PUBLIC 0
#define BLE_HS_EALREADY 2
#define BLE_HS_CONN_HANDLE_NONE 65535
#define BLE_ERR_REM_USER_CONN_TERM 19
#define BLE_GAP_EVENT_DISC 1
#define BLE_GAP_EVENT_DISC_COMPLETE 2
#define BLE_GAP_EVENT_CONNECT 3
#define BLE_GAP_EVENT_NOTIFY_RX 4
#define BLE_GAP_EVENT_DISCONNECT 5
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
#define portMAX_DELAY 0xffffffff
#define pdMS_TO_TICKS(x) (x)
typedef struct { uint8_t type, val[6]; } ble_addr_t;
struct ble_hs_adv_fields { const uint8_t *name, *mfg_data; int name_len, mfg_data_len; };
struct ble_gap_event {
 int type;
 struct { uint8_t *data; int length_data, rssi; ble_addr_t addr; } disc;
 struct { int reason; } disc_complete, disconnect;
 struct { int status; uint16_t conn_handle; } connect;
 struct { uint16_t conn_handle, attr_handle; void *om; } notify_rx;
};
static bool s_connected, s_scanning, s_peer_addr_valid, s_notify_subscribed;
static uint16_t s_conn_handle, s_combo_svc_end_handle, s_combo_val_handle, s_combo_cccd_handle;
static ble_addr_t s_peer_addr, last_connected, saved;
static int s_conn_params, s_disc_params, s_health, s_source;
static void *s_reconnect_sem = (void*)1;
static struct { int u; } svc_combo_uuid;
static int connect_calls, scan_calls, stores, svc_calls, gives, connect_rc;
static int mode, phase, takes, delayed, first_scan_delay;
static jmp_buf stop;
static struct ble_hs_adv_fields advertisement;
static int gap_event_cb(struct ble_gap_event*, void*);
static void disc_svc_cb(void) {}
static int ble_gap_connect(int own, const ble_addr_t *addr, int duration, void *params, int (*cb)(struct ble_gap_event*,void*),void *arg) {
 (void)own;(void)duration;(void)params;(void)cb;(void)arg;
 connect_calls++; last_connected=*addr; return connect_rc;
}
static int ble_gap_disc(int own,int duration,void *params,int (*cb)(struct ble_gap_event*,void*),void *arg) {
 (void)own;(void)duration;(void)params;(void)cb;(void)arg;
 scan_calls++; first_scan_delay=delayed; return 0;
}
static int ble_hs_adv_parse_fields(struct ble_hs_adv_fields *out,void *data,int len) {
 (void)data;(void)len;*out=advertisement;return 0;
}
static int ble_gap_disc_cancel(void) {return 0;}
static bool nvs_store_addr(const ble_addr_t *addr) {stores++;saved=*addr;return true;}
static void invalidate_health(int *p) {*p=0;}
static bool health_source_connect(int *p) {(void)p;return true;}
static int ble_gap_terminate(int handle,int reason) {(void)handle;(void)reason;return 0;}
static int ble_gattc_disc_svc_by_uuid(int handle,void *uuid,void (*cb)(void),void *arg) {
 (void)handle;(void)uuid;(void)cb;(void)arg;svc_calls++;return 0;
}
static void xSemaphoreGive(void *sem) {(void)sem;gives++;}
static int os_mbuf_copydata(void *om,int offset,int len,void *out) {(void)om;(void)offset;(void)len;(void)out;return -1;}
static void cache_frame(const uint8_t *frame) {(void)frame;}
static void invalidate_cache(void) {}
static void xSemaphoreTake(void *sem,unsigned timeout) {(void)sem;(void)timeout;if(takes++)longjmp(stop,1);}
static void connect_event(int status) {
 struct ble_gap_event e={.type=BLE_GAP_EVENT_CONNECT,.connect={.status=status,.conn_handle=7}};
 gap_event_cb(&e,NULL);
}
static void adv_event(void) {
 struct ble_gap_event e={.type=BLE_GAP_EVENT_DISC,.disc={.addr={.type=1,.val={6,5,4,3,2,1}}}};
 gap_event_cb(&e,NULL);
}
static void vTaskDelay(int ms) {
 delayed+=ms;
 if(mode==1 && phase==0 && connect_calls==1) {phase=1;connect_event(13);}
 else if(mode==1 && scan_calls==1 && phase==1) {phase=2;adv_event();connect_event(0);}
 else if(mode==2 && connect_calls==1 && scan_calls==0) {connect_event(0);}
 else if(mode==3 && scan_calls==1) {connect_rc=0;adv_event();connect_event(0);}
 if(mode==4 && scan_calls>0 && !s_connected) {
  if(scan_calls<3 && s_scanning) {struct ble_gap_event e={.type=BLE_GAP_EVENT_DISC_COMPLETE};gap_event_cb(&e,NULL);}
  else if(scan_calls==3) {adv_event();connect_event(0);}
 }
 if(delayed>100000) {fprintf(stderr,"reconnect did not scan within existing retries\n");longjmp(stop,2);}
}
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
        s_peer_addr_valid = false;  /* Next retry uses the existing scan path. */
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
            portENTER_CRITICAL(&s_cache_mux);
            invalidate_health(&s_health);
            s_connected = health_source_connect(&s_source);
            portEXIT_CRITICAL(&s_cache_mux);
            if (!s_connected) {
                (void)ble_gap_terminate(s_conn_handle, BLE_ERR_REM_USER_CONN_TERM);
                return 0;
            }
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
            s_peer_addr_valid = false;  /* Keep NVS; rediscover on the next retry. */
            s_connected = false;
            s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            if (s_reconnect_sem) {
                xSemaphoreGive(s_reconnect_sem);
            }
        }
        return 0;

    /* ---- notify 数据（IDF NimBLE 事件名 NOTIFY_RX） ---- */
    case BLE_GAP_EVENT_NOTIFY_RX:
        if (s_connected && event->notify_rx.conn_handle == s_conn_handle &&
            event->notify_rx.attr_handle == s_combo_val_handle) {
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

static void on_sync(void)
{
    ESP_LOGI(TAG, "NimBLE 主机同步完成");
    if (s_peer_addr_valid) {
        ESP_LOGI(TAG, "已存对端地址，尝试开机直连");
        if (s_reconnect_sem) {
            xSemaphoreGive(s_reconnect_sem);
        }
    } else {
        ESP_LOGI(TAG, "无对端地址，启动后台自动扫描");
        if (s_reconnect_sem) {
            xSemaphoreGive(s_reconnect_sem);
        }
    }
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


static void reset(void) {
 s_connected=false;s_scanning=false;s_peer_addr_valid=true;s_peer_addr=(ble_addr_t){.type=0,.val={1,2,3,4,5,6}};
 connect_calls=scan_calls=stores=svc_calls=gives=connect_rc=phase=takes=delayed=first_scan_delay=0;
 static const uint8_t name[]="WH-Wrist01",mfg[]={255,255,3};
 advertisement=(struct ble_hs_adv_fields){name,mfg,10,3};
}
static void run_task(void) {int result=setjmp(stop);if(!result)reconnect_task(NULL);else assert(result==1);}
int main(void) {
 reset();s_peer_addr_valid=false;mode=3;on_sync();
 assert(gives==1 && scan_calls==0 && connect_calls==0);
 run_task();assert(scan_calls==1 && connect_calls==1 && svc_calls==1 && first_scan_delay==0);
 puts("PASS no saved address boot wakes background scan and connects without key");
 reset();mode=2;on_sync();assert(gives==1 && !scan_calls && !connect_calls);
 run_task();assert(connect_calls==1 && !scan_calls);
 puts("PASS saved address boot preserves direct connect priority");
 reset();s_peer_addr_valid=false;mode=4;on_sync();assert(gives==1);
 run_task();assert(scan_calls==3 && first_scan_delay==30000 && connect_calls==1 && s_connected);
 puts("PASS two empty scan windows retain backoff then late device connects");
 int scans_before=scan_calls,connects_before=connect_calls;
 ble_central_start_scan();assert(scan_calls==scans_before && connect_calls==connects_before);
 puts("PASS connected device is not scanned or preempted");

 reset();mode=2;on_sync();run_task();
 ble_addr_t first_peer=last_connected;
 struct ble_gap_event lost={.type=BLE_GAP_EVENT_DISCONNECT,.disconnect={.reason=19}};
 gap_event_cb(&lost,NULL);assert(!s_connected && s_peer_addr_valid);
 connect_calls=scan_calls=stores=svc_calls=phase=takes=delayed=first_scan_delay=0;
 mode=1;run_task();
 assert(s_connected && scan_calls==1 && connect_calls==2 && stores==1 && svc_calls==1);
 assert(memcmp(&first_peer,&last_connected,sizeof(first_peer))!=0);
 puts("PASS disconnected first node unavailable -> rescan -> distinct compatible second node");
 reset();mode=1;run_task();
 assert(connect_calls==2 && scan_calls==1 && stores==1 && svc_calls==1);
 assert(first_scan_delay==14000 && s_connected && s_peer_addr_valid);
 assert(!memcmp(&saved,&last_connected,sizeof(saved)) && saved.type==1);
 puts("PASS async rc13 -> original 12s wait + 2s backoff -> scan -> save -> connect -> service discovery");
 reset();mode=2;run_task();assert(connect_calls==1 && !scan_calls && !stores && svc_calls==1);
 puts("PASS remembered first connection remains direct");
 struct ble_gap_event e={.type=BLE_GAP_EVENT_DISCONNECT,.disconnect={.reason=19}};
 gap_event_cb(&e,NULL);assert(s_peer_addr_valid && !s_connected);
 connect_calls=scan_calls=svc_calls=takes=delayed=0;run_task();
 assert(connect_calls==1 && !scan_calls && svc_calls==1);
 puts("PASS normal disconnect reconnects directly");
 reset();mode=3;connect_rc=7;run_task();
 assert(scan_calls==1 && stores==1 && connect_calls==2 && svc_calls==1 && first_scan_delay==14000);
 puts("PASS synchronous connect failure -> existing backoff -> scan -> connection");
 reset();connect_rc=BLE_HS_EALREADY;start_connect(&s_peer_addr);assert(s_peer_addr_valid);
 puts("PASS already-connecting result retains current peer");
 reset();s_peer_addr_valid=false;
 static const uint8_t wrong_name[]="XX-Wrist01", right_name[]="WH-Wrist01", wrong_company[]={0,0,3}, partial_caps[]={255,255,1}, good[]={255,255,3};
 advertisement.name=wrong_name;adv_event();
 advertisement.name=right_name;advertisement.mfg_data=wrong_company;adv_event();
 advertisement.mfg_data=partial_caps;adv_event();
 assert(!connect_calls && !stores && !s_peer_addr_valid);
 advertisement.mfg_data=good;adv_event();assert(connect_calls==1 && stores==1 && s_peer_addr_valid);
 puts("PASS discovery rejects wrong name/company/capabilities and accepts valid wrist node");
 return 0;
}
