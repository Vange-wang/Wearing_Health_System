/*
 * SPDX-License-Identifier: CC0-1.0
 *
 * ble_central — P2/P3 BOX-3 BLE central（zcode, 2026-08-23）
 *
 * 功能（任务单 2026-08-23-P2/P3-BOX3-BLEcentral）：
 *   1. 扫描匹配腕部节点 WH-Wrist01（名字前缀 WH- + 厂商段 0xFFFF 能力位 bit0/bit1）
 *   2. 连接 → 服务发现（combo 0x7a0b1000…）→ 订阅综合帧特征 notify（0x7a0b1001…）
 *   3. 8 字节帧解析缓存（seq 丢帧检测 / HR-uint16LE / SpO2 / conf / flags / battery）
 *   4. NVS 存两个已订阅地址 → 开机直连与后台扫描；各节点独立生命周期
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
#include "health_source.h"
#include "ble_peer_state.h"
#include "nimble/nimble_npl.h"
#include "sdkconfig.h"
_Static_assert(CONFIG_BT_NIMBLE_MAX_CONNECTIONS>=2,"BLE two-peer configuration required");
#include <inttypes.h>
#include "esp_random.h"
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
#include "service_origin.h"

static const char *TAG = "ble_central";

/* ---- P3 上报（任务单 2026-08-23-P3）：与 HEALTH_URL 同域，mDNS 由 voice_agent 初始化 ---- */
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

/* All GAP/GATT control below runs on the NimBLE host event queue.
 * Cache/source selection is mirrored under the existing short cache critical section. */
static portMUX_TYPE s_cache_mux=portMUX_INITIALIZER_UNLOCKED;
static ble_peer_bank_t s_bank;
static char s_boot_id[33];
static SemaphoreHandle_t s_reconnect_sem,s_upload_sem;
static struct ble_npl_event s_poll_event;
static bool s_synced,s_scanning;
static uint64_t s_next_scan;
static unsigned s_scan_failures;
static uint32_t s_scan_token;
typedef struct {uint16_t svc_end,value,cccd;uint8_t stage;uint64_t deadline;} peer_gatt_t;
static peer_gatt_t s_gatt[BP_COUNT];
typedef struct {uint8_t type,val[6];} peer_addr_record_t;
typedef struct {uint8_t version,count;peer_addr_record_t addr[2];} saved_peers_t;
static saved_peers_t s_saved;
static unsigned s_hint_index;
static int gap_event_cb(struct ble_gap_event *,void *);
static int disc_svc_cb(uint16_t,const struct ble_gatt_error *,const struct ble_gatt_svc *,void *);
static int disc_chr_cb(uint16_t,const struct ble_gatt_error *,const struct ble_gatt_chr *,void *);
static int disc_dsc_cb(uint16_t,const struct ble_gatt_error *,uint16_t,const struct ble_gatt_dsc *,void *);
static int cccd_write_cb(uint16_t,const struct ble_gatt_error *,struct ble_gatt_attr *,void *);
static uint64_t now_us(void){return (uint64_t)esp_timer_get_time();}
static void wake_background(void){if(s_reconnect_sem)xSemaphoreGive(s_reconnect_sem);if(s_upload_sem)xSemaphoreGive(s_upload_sem);}
static uint32_t callback_token(void *arg){return (uint32_t)(uintptr_t)arg;}
static void *callback_arg(uint32_t token){return (void *)(uintptr_t)token;}
static bool required_caps_present(uint8_t capabilities){return (capabilities&TARGET_MFG_CAPS)==TARGET_MFG_CAPS;}
static int current(uint32_t token,uint16_t handle){return bp_find(&s_bank,token,handle);}
static int callback_peer(uint16_t handle,void *arg,unsigned stage){int i=current(callback_token(arg),handle);return i>=0 && s_bank.peer[i].phase==BP_DISCOVERING && s_gatt[i].stage==stage?i:-1;}
static void load_saved(void){
 nvs_handle_t h;if(nvs_open(NVS_NS,NVS_READONLY,&h)!=ESP_OK)return;
 size_t len=sizeof(s_saved);bool ok=nvs_get_blob(h,"peer_addrs",&s_saved,&len)==ESP_OK && len==sizeof(s_saved) && s_saved.version==1 && s_saved.count<=2;
 if(ok)for(unsigned i=0;i<s_saved.count;i++)if(s_saved.addr[i].type>BLE_ADDR_RANDOM_ID)ok=false;
 if(!ok){memset(&s_saved,0,sizeof(s_saved));peer_addr_record_t old={0};len=sizeof(old);
  ok=nvs_get_blob(h,NVS_KEY_ADDR,&old,&len)==ESP_OK && len==sizeof(old) && old.type<=BLE_ADDR_RANDOM_ID;
  if(!ok){len=6;old.type=BLE_ADDR_PUBLIC;ok=nvs_get_blob(h,NVS_KEY_MAC_LEGACY,old.val,&len)==ESP_OK && len==6;}
  if(ok){s_saved.version=1;s_saved.count=1;s_saved.addr[0]=old;}
 }
 nvs_close(h); /* no migration writes at boot */
}
static void save_confirmed(unsigned slot){
 ble_peer_t *p=&s_bank.peer[slot];peer_addr_record_t a={.type=p->address_type};memcpy(a.val,p->address,6);
 for(unsigned i=0;i<s_saved.count;i++)if(!memcmp(&a,&s_saved.addr[i],sizeof(a)))return;
 saved_peers_t next=s_saved;
 if(next.count<2)next.addr[next.count++]=a;else{next.addr[0]=next.addr[1];next.addr[1]=a;}next.version=1;
 nvs_handle_t h;if(nvs_open(NVS_NS,NVS_READWRITE,&h)!=ESP_OK)return;
 esp_err_t rc=nvs_set_blob(h,"peer_addrs",&next,sizeof(next));if(rc==ESP_OK)rc=nvs_commit(h);nvs_close(h);if(rc==ESP_OK)s_saved=next;
 ESP_LOGI(TAG,"ble2:saved count=%u rc=%d",s_saved.count,rc);
}
static void release_peer(uint32_t token){
 portENTER_CRITICAL(&s_cache_mux);bp_drop(&s_bank,token,now_us());portEXIT_CRITICAL(&s_cache_mux);wake_background();
}
static void fail_peer(unsigned slot){
 ble_peer_t *p=&s_bank.peer[slot];if(p->phase==BP_FREE)return;
 portENTER_CRITICAL(&s_cache_mux);p->phase=BP_CLOSING;p->have_good=false;bp_select(&s_bank,now_us());portEXIT_CRITICAL(&s_cache_mux);
 s_gatt[slot].deadline=now_us()+2000000ULL;
 if(p->handle==BLE_HS_CONN_HANDLE_NONE)(void)ble_gap_conn_cancel();
 else (void)ble_gap_terminate(p->handle,BLE_ERR_REM_USER_CONN_TERM);
 /* Keep slot/token until actual disconnect/connect-failure callback. */
 wake_background();
}
static void begin_connect(const ble_addr_t *addr){
 portENTER_CRITICAL(&s_cache_mux);int i=bp_reserve(&s_bank,addr->type,addr->val);portEXIT_CRITICAL(&s_cache_mux);if(i<0)return;
 memset(&s_gatt[i],0,sizeof(s_gatt[i]));s_gatt[i].deadline=now_us()+12000000ULL;
 uint32_t token=s_bank.peer[i].token;
 int rc=ble_gap_connect(BLE_OWN_ADDR_PUBLIC,addr,SCAN_DURATION_MS,&s_conn_params,gap_event_cb,callback_arg(token));
 if(rc!=0){release_peer(token);s_next_scan=now_us()+2000000ULL;}
}
static int cccd_write_cb(uint16_t handle,const struct ble_gatt_error *error,struct ble_gatt_attr *attr,void *arg){
 (void)attr;int i=callback_peer(handle,arg,4);if(i<0)return 0;
 if(error->status){fail_peer((unsigned)i);return 0;}
 portENTER_CRITICAL(&s_cache_mux);bool ok=bp_ready(&s_bank,callback_token(arg),handle);portEXIT_CRITICAL(&s_cache_mux);
 if(ok){s_gatt[i].deadline=0;s_scan_failures=0;save_confirmed((unsigned)i);ESP_LOGI(TAG,"ble2:ready slot=%d token=%lu handle=%u",i,(unsigned long)callback_token(arg),handle);wake_background();}return 0;
}
static int disc_dsc_cb(uint16_t handle,const struct ble_gatt_error *error,uint16_t val,const struct ble_gatt_dsc *dsc,void *arg){
 int i=callback_peer(handle,arg,3);if(i<0)return 0;
 if(error->status==0 && val!=s_gatt[i].value)return 0;
 if(error->status==0 && dsc && ble_uuid_cmp(&dsc->uuid.u,&dsc_cccd_uuid.u)==0){
  s_gatt[i].cccd=dsc->handle;s_gatt[i].stage=4;s_gatt[i].deadline=now_us()+10000000ULL;
  const uint8_t value[2]={1,0};if(ble_gattc_write_flat(handle,dsc->handle,value,2,cccd_write_cb,arg)!=0)fail_peer((unsigned)i);
 }else if(error->status)fail_peer((unsigned)i);return 0;
}
static int disc_chr_cb(uint16_t handle,const struct ble_gatt_error *error,const struct ble_gatt_chr *chr,void *arg){
 int i=callback_peer(handle,arg,2);if(i<0)return 0;
 if(error->status==0 && chr && ble_uuid_cmp(&chr->uuid.u,&chr_combo_uuid.u)==0){
  if(!(chr->properties & BLE_GATT_CHR_PROP_NOTIFY)){fail_peer((unsigned)i);return 0;}
  s_gatt[i].value=chr->val_handle;s_gatt[i].stage=3;s_gatt[i].deadline=now_us()+10000000ULL;
  if(ble_gattc_disc_all_dscs(handle,chr->val_handle,s_gatt[i].svc_end,disc_dsc_cb,arg)!=0)fail_peer((unsigned)i);
 }else if(error->status)fail_peer((unsigned)i);return 0;
}
static int disc_svc_cb(uint16_t handle,const struct ble_gatt_error *error,const struct ble_gatt_svc *svc,void *arg){
 int i=callback_peer(handle,arg,1);if(i<0)return 0;
 if(error->status==0 && svc && ble_uuid_cmp(&svc->uuid.u,&svc_combo_uuid.u)==0){
  s_gatt[i].svc_end=svc->end_handle;s_gatt[i].stage=2;s_gatt[i].deadline=now_us()+10000000ULL;
  if(ble_gattc_disc_chrs_by_uuid(handle,svc->start_handle,svc->end_handle,&chr_combo_uuid.u,disc_chr_cb,arg)!=0)fail_peer((unsigned)i);
 }else if(error->status)fail_peer((unsigned)i);return 0;
}
static int gap_event_cb(struct ble_gap_event *event,void *arg){
 uint32_t token=callback_token(arg);
 switch(event->type){
 case BLE_GAP_EVENT_DISC:{
  if(!s_scanning || token!=s_scan_token)return 0;
  struct ble_hs_adv_fields f;if(ble_hs_adv_parse_fields(&f,event->disc.data,event->disc.length_data))return 0;
  if(!f.name || f.name_len<3 || memcmp(f.name,TARGET_NAME_PREFIX,3) || !f.mfg_data || f.mfg_data_len<3 || f.mfg_data[0]!=255 || f.mfg_data[1]!=255 || !required_caps_present(f.mfg_data[2]))return 0;
  for(unsigned i=0;i<BP_COUNT;i++)if(s_bank.peer[i].phase!=BP_FREE && s_bank.peer[i].address_type==event->disc.addr.type && !memcmp(s_bank.peer[i].address,event->disc.addr.val,6))return 0;
  if(ble_gap_disc_cancel()!=0) {
   return 0;
  }
  s_scanning=false;
  begin_connect(&event->disc.addr);
  return 0;
 }
 case BLE_GAP_EVENT_DISC_COMPLETE:if(token!=s_scan_token)return 0;s_scanning=false;s_next_scan=now_us()+2000000ULL;wake_background();return 0;
 case BLE_GAP_EVENT_CONNECT:{
  int i=current(token,BLE_HS_CONN_HANDLE_NONE);if(i<0)return 0;
  if(event->connect.status){release_peer(token);s_next_scan=now_us()+2000000ULL;return 0;}
  if(s_bank.peer[i].phase==BP_CLOSING){portENTER_CRITICAL(&s_cache_mux);s_bank.peer[i].handle=event->connect.conn_handle;portEXIT_CRITICAL(&s_cache_mux);fail_peer((unsigned)i);return 0;}
  portENTER_CRITICAL(&s_cache_mux);bool ok=bp_connected(&s_bank,token,event->connect.conn_handle);portEXIT_CRITICAL(&s_cache_mux);
  if(!ok){(void)ble_gap_terminate(event->connect.conn_handle,BLE_ERR_REM_USER_CONN_TERM);return 0;}
  s_gatt[i].stage=1;s_gatt[i].deadline=now_us()+10000000ULL;
  if(ble_gattc_disc_svc_by_uuid(event->connect.conn_handle,&svc_combo_uuid.u,disc_svc_cb,arg)!=0) {
   fail_peer((unsigned)i);
  }
  return 0;
 }
 case BLE_GAP_EVENT_NOTIFY_RX:{
  int i=current(token,event->notify_rx.conn_handle);if(i<0 || s_bank.peer[i].phase!=BP_READY || event->notify_rx.attr_handle!=s_gatt[i].value)return 0;
  uint8_t frame[8];if(OS_MBUF_PKTLEN(event->notify_rx.om)!=8 || os_mbuf_copydata(event->notify_rx.om,0,8,frame))return 0;
  portENTER_CRITICAL(&s_cache_mux);health_source_result_t r=bp_frame(&s_bank,token,event->notify_rx.conn_handle,frame,now_us());ble_node_snapshot_t snap;bp_snapshot(&s_bank,(unsigned)i,&snap);portEXIT_CRITICAL(&s_cache_mux);
  if(r==HEALTH_SOURCE_AMBIGUOUS || r==HEALTH_SOURCE_CAPACITY)fail_peer((unsigned)i);
  if(r==HEALTH_SOURCE_NEW){ESP_LOGI(TAG,"ble2:frame slot=%d token=%lu conn=%u gen=%" PRIu64 " index=%" PRIu64 " age_ms=0 selected=%u upload=%" PRIu64 " seq=%u flags=%u hr=%u spo2=%u conf=%u",i,(unsigned long)token,snap.conn_handle,snap.latest.source_generation,snap.latest.source_index,snap.selected?1U:0U,snap.upload_generation,snap.latest.seq,snap.latest.flags,snap.latest.hr,snap.latest.spo2,snap.latest.conf);if(s_upload_sem)xSemaphoreGive(s_upload_sem);}return 0;
 }
 case BLE_GAP_EVENT_DISCONNECT:if(current(token,event->disconnect.conn.conn_handle)>=0)release_peer(token);return 0;
 default:return 0;
 }
}
static void poll_host(struct ble_npl_event *ev){
 (void)ev;if(!s_synced)return;uint64_t now=now_us();
 portENTER_CRITICAL(&s_cache_mux);bp_select(&s_bank,now);portEXIT_CRITICAL(&s_cache_mux);
 if(s_upload_sem)xSemaphoreGive(s_upload_sem);
 unsigned used=0;bool busy=false;
 for(unsigned i=0;i<BP_COUNT;i++)if(s_bank.peer[i].phase!=BP_FREE){used++;if(s_bank.peer[i].phase!=BP_READY)busy=true;if(s_gatt[i].deadline && now>=s_gatt[i].deadline)fail_peer(i);}
 if(used==BP_COUNT){if(s_scanning){(void)ble_gap_disc_cancel();s_scanning=false;}return;}
 if(busy || s_scanning || now<s_next_scan)return;
 while(s_hint_index<s_saved.count){peer_addr_record_t *a=&s_saved.addr[s_hint_index++];bool duplicate=false;
  for(unsigned i=0;i<BP_COUNT;i++)if(s_bank.peer[i].phase!=BP_FREE && s_bank.peer[i].address_type==a->type && !memcmp(s_bank.peer[i].address,a->val,6))duplicate=true;
  if(!duplicate){ble_addr_t addr={.type=a->type};memcpy(addr.val,a->val,6);begin_connect(&addr);return;}
 }
 if(s_scan_token==UINT32_MAX)return;
 ++s_scan_token;
 int rc=ble_gap_disc(BLE_OWN_ADDR_PUBLIC,SCAN_DURATION_MS,&s_disc_params,gap_event_cb,callback_arg(s_scan_token));
 if(rc==0)s_scanning=true;else{if(s_scan_failures<4)s_scan_failures++;s_next_scan=now+(2000000ULL<<s_scan_failures);}
}
static void reconnect_task(void *arg){
 (void)arg;for(;;){xSemaphoreTake(s_reconnect_sem,pdMS_TO_TICKS(500));ble_npl_eventq_put(nimble_port_get_dflt_eventq(),&s_poll_event);}
}
static bool source_is_current(const ble_health_t *h){
 portENTER_CRITICAL(&s_cache_mux);bool ok=bp_current(&s_bank,h);portEXIT_CRITICAL(&s_cache_mux);return ok;
}
static bool http_post_health(const ble_health_t *h)
{
    /* 无效字段传 null（服务端 Pydantic 可空；None 不覆盖值） */
    if (!source_is_current(h)) return false;
    char body[320];
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

    uint64_t now_us = (uint64_t)esp_timer_get_time();
    if (now_us < h->source_received_us) return false;
    uint64_t age_ms = (now_us - h->source_received_us) / 1000;
    if (age_ms > INT64_MAX) return false;
    size_t prefix = strlen(body);
    int appended = snprintf(body + prefix - 1, sizeof(body) - prefix + 1,
        ",\"source_epoch\":\"%s:%" PRIu64 "\",\"source_index\":%" PRIu64
        ",\"source_age_ms\":%" PRIu64 "}",
        s_boot_id, h->upload_generation, h->source_index, age_ms);
    if (appended < 0 || (size_t)appended >= sizeof(body) - prefix + 1) return false;

    service_origin_snapshot_t origin;char origin_url[96];
    if(!service_origin_acquire(&origin,true) || !service_origin_url(&origin,ORIGIN_DATA,origin_url,sizeof(origin_url)))return false;
    esp_http_client_config_t cfg = {
        .url = origin_url,
        .disable_auto_redirect = true,
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
        source_is_current(h) &&
        service_origin_current(&origin) &&
        esp_http_client_write(client, body, wlen) >= 0 &&
        esp_http_client_fetch_headers(client) >= 0 &&
        esp_http_client_get_status_code(client) == 200) {
        ok = true;
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return ok && service_origin_current(&origin);
}

static void upload_task(void *arg)
{
    (void)arg;
    int fail_streak = 0;
    bool first_upload_done = false;
    uint64_t sent_epoch=0,sent_index=0;
    while (1) {
        xSemaphoreTake(s_upload_sem, portMAX_DELAY);
        ble_health_t h;
        if (!ble_central_get_data(&h)) {
            continue;
        }
        if(first_upload_done && sent_epoch==h.upload_generation && sent_index==h.source_index)continue;
        bool ok = false;
        for (int attempt = 0; attempt < 2 && !ok; attempt++) {   /* 首次 + 重试 1 次 */
            if (!source_is_current(&h)) break;
            ok = http_post_health(&h);
            if (!ok && attempt == 0) {
                vTaskDelay(pdMS_TO_TICKS(UPLOAD_RETRY_MS));
            }
        }
        if (ok) {
            sent_epoch=h.upload_generation;sent_index=h.source_index;
            portENTER_CRITICAL(&s_cache_mux);bp_uploaded(&s_bank,&h);portEXIT_CRITICAL(&s_cache_mux);
            if(s_upload_sem)xSemaphoreGive(s_upload_sem);
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

static void on_sync(void){s_synced=true;wake_background();}
static void on_reset(int reason){
 (void)reason;s_synced=false;s_scanning=false;portENTER_CRITICAL(&s_cache_mux);
 for(unsigned i=0;i<BP_COUNT;i++)if(s_bank.peer[i].phase!=BP_FREE)bp_drop(&s_bank,s_bank.peer[i].token,now_us());
 portEXIT_CRITICAL(&s_cache_mux);wake_background();
}
static void nimble_host_task(void *param){(void)param;nimble_port_run();nimble_port_freertos_deinit();}
esp_err_t ble_central_init(void){
 bp_init(&s_bank);uint8_t random[16];static const char hex[]="0123456789abcdef";esp_fill_random(random,sizeof(random));
 for(unsigned i=0;i<16;i++){s_boot_id[i*2]=hex[random[i]>>4];s_boot_id[i*2+1]=hex[random[i]&15];}s_boot_id[32]=0;
 load_saved();s_reconnect_sem=xSemaphoreCreateBinary();s_upload_sem=xSemaphoreCreateBinary();if(!s_reconnect_sem || !s_upload_sem)return ESP_ERR_NO_MEM;
 int rc=nimble_port_init();if(rc!=ESP_OK)return rc;
 ble_hs_cfg.reset_cb=on_reset;ble_hs_cfg.sync_cb=on_sync;ble_hs_cfg.store_status_cb=ble_store_util_status_rr;ble_hs_cfg.gatts_register_cb=NULL;
 ble_npl_event_init(&s_poll_event,poll_host,NULL);
 if(xTaskCreate(reconnect_task,"ble_reconn",4096,NULL,4,NULL)!=pdPASS)return ESP_ERR_NO_MEM;
 if(xTaskCreateWithCaps(upload_task,"ble_upload",4096,NULL,4,NULL,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)!=pdPASS)return ESP_ERR_NO_MEM;
 nimble_port_freertos_init(nimble_host_task);return ESP_OK;
}
void ble_central_start_scan(void){if(s_reconnect_sem)xSemaphoreGive(s_reconnect_sem);}
bool ble_central_is_connected(void){bool ok=false;portENTER_CRITICAL(&s_cache_mux);for(unsigned i=0;i<BP_COUNT;i++)if(s_bank.peer[i].phase==BP_READY)ok=true;portEXIT_CRITICAL(&s_cache_mux);return ok;}
bool ble_central_get_data(ble_health_t *out){if(!out)return false;portENTER_CRITICAL(&s_cache_mux);bool ok=s_bank.output_valid;if(ok)*out=s_bank.output;portEXIT_CRITICAL(&s_cache_mux);return ok;}
bool ble_central_get_node_data(unsigned slot,ble_node_snapshot_t *out){if(!out || slot>=BP_COUNT)return false;portENTER_CRITICAL(&s_cache_mux);bp_snapshot(&s_bank,slot,out);portEXIT_CRITICAL(&s_cache_mux);return true;}
