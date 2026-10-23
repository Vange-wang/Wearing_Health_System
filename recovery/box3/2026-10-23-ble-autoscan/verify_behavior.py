from pathlib import Path
import hashlib
import sys

root = Path(__file__).resolve().parent
source_path = Path(sys.argv[1]) if len(sys.argv)>1 else root/'source/main/ble_central.c'
source = source_path.read_text(encoding='utf-8')
# Compile the verbatim production GAP callbacks and reconnect task, with host API doubles.
section = source[source.index('static bool required_caps_present('):source.index('/* ---------------- P3 上报任务')]
section += source[source.index('static void on_sync(void)'):source.index('static void nimble_host_task(')]
section += source[source.index('void ble_central_start_scan(void)'):source.index('bool ble_central_is_connected(void)')]
prefix = r'''
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
'''
suffix = r'''
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
'''
(root / 'behavior_host.c').write_text(prefix + section + suffix, encoding='utf-8')
print('Generated host harness from candidate actual functions; source SHA256:', hashlib.sha256(source_path.read_bytes()).hexdigest())
