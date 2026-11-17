#include "ble_peer_state.h"
#include <string.h>
void bp_init(ble_peer_bank_t *b){memset(b,0,sizeof(*b));b->selected=-1;}
int bp_find(ble_peer_bank_t *b,uint32_t token,uint16_t handle){
 for(unsigned i=0;i<BP_COUNT;i++)if(token && b->peer[i].token==token && b->peer[i].phase!=BP_FREE && b->peer[i].handle==handle)return (int)i;
 return -1;
}
int bp_reserve(ble_peer_bank_t *b,uint8_t type,const uint8_t address[6]){
 int slot=-1;
 for(unsigned i=0;i<BP_COUNT;i++){
  if(b->peer[i].phase!=BP_FREE && b->peer[i].address_type==type && !memcmp(b->peer[i].address,address,6))return -1;
  if(b->peer[i].phase==BP_FREE && slot<0)slot=(int)i;
 }
 if(slot<0 || b->next_token==UINT32_MAX)return -1;
 ble_peer_t *p=&b->peer[slot];uint64_t gen=p->source.generation;
 memset(p,0,sizeof(*p));p->source.generation=gen;p->token=++b->next_token;
 p->address_type=type;memcpy(p->address,address,6);p->handle=UINT16_MAX;p->phase=BP_CONNECTING;return slot;
}
bool bp_connected(ble_peer_bank_t *b,uint32_t token,uint16_t handle){
 int i=bp_find(b,token,UINT16_MAX);if(i<0 || b->peer[i].phase!=BP_CONNECTING)return false;
 ble_peer_t *p=&b->peer[i];if(!health_source_connect(&p->source))return false;p->handle=handle;p->phase=BP_DISCOVERING;return true;
}
bool bp_ready(ble_peer_bank_t *b,uint32_t token,uint16_t handle){int i=bp_find(b,token,handle);if(i<0 || b->peer[i].phase!=BP_DISCOVERING)return false;b->peer[i].phase=BP_READY;return true;}
static bool eligible(const ble_peer_t *p,uint64_t now){return p->phase==BP_READY && p->have_good && now>=p->good_us && now-p->good_us<=BP_FRESH_US;}
void bp_select(ble_peer_bank_t *b,uint64_t now){
 int pick=b->selected;
 if(pick<0 || b->peer[pick].token!=b->selected_token || !eligible(&b->peer[pick],now)){
  pick=-1;for(unsigned i=0;i<BP_COUNT;i++)if(eligible(&b->peer[i],now)){pick=(int)i;break;}
 }
 if(pick<0){b->selected=-1;b->selected_token=0;b->output_valid=false;return;}
 ble_peer_t *p=&b->peer[pick];
 if(pick!=b->selected || p->token!=b->selected_token){
  if(b->output_epoch==UINT64_MAX){b->output_valid=false;return;}
  ++b->output_epoch;b->handover_pending=true;b->selected=pick;b->selected_token=p->token;
 }
 b->output=b->handover_pending?p->good:p->latest;b->output.upload_generation=b->output_epoch;b->output_valid=b->output.valid;
}
void bp_drop(ble_peer_bank_t *b,uint32_t token,uint64_t now){
 for(unsigned i=0;i<BP_COUNT;i++)if(b->peer[i].token==token && b->peer[i].phase!=BP_FREE){ble_peer_t *p=&b->peer[i];health_source_disconnect(&p->source);p->phase=BP_FREE;p->latest.valid=false;p->have_good=false;break;}
 bp_select(b,now);
}
health_source_result_t bp_frame(ble_peer_bank_t *b,uint32_t token,uint16_t handle,const uint8_t f[8],uint64_t now){
 int i=bp_find(b,token,handle);if(i<0 || b->peer[i].phase!=BP_READY)return HEALTH_SOURCE_DISCONNECTED;
 ble_peer_t *p=&b->peer[i];bool had=p->source.have_seq;uint8_t old=p->source.seq;
 health_source_result_t r=health_source_accept(&p->source,f[0],now);if(r!=HEALTH_SOURCE_NEW)return r;
 uint32_t lost=p->latest.lost;if(had)lost+=(uint8_t)(f[0]-old)-1U;
 ble_health_t h={0};h.seq=f[0];h.flags=f[1];h.hr=(uint16_t)f[2]|((uint16_t)f[3]<<8);h.spo2=f[4];h.conf=f[5];h.battery=f[6];h.ts_ms=(uint32_t)(now/1000);h.lost=lost;h.valid=true;
 h.source_generation=p->source.generation;h.source_index=p->source.index;h.source_received_us=p->source.first_received_us;h.node_token=token;h.node_slot=(uint8_t)i;p->latest=h;
 bool range_ok=(!(h.flags&1U)||(h.hr>=20 && h.hr<=250)) && (!(h.flags&2U)||(h.spo2>=50 && h.spo2<=100));
 if((h.flags&3U) && !(h.flags&4U) && h.conf>=50 && h.conf<=100 && range_ok){p->have_good=true;p->good_us=now;p->good=h;}
 bp_select(b,now);return r;
}
bool bp_current(ble_peer_bank_t *b,const ble_health_t *h){
 if(!h || !b->output_valid || b->selected!=(int)h->node_slot || b->selected_token!=h->node_token || b->output_epoch!=h->upload_generation)return false;
 ble_peer_t *p=&b->peer[h->node_slot];return p->phase==BP_READY && health_source_current(&p->source,h->source_generation);
}
void bp_uploaded(ble_peer_bank_t *b,const ble_health_t *h){
 if(!bp_current(b,h))return;
 if(b->handover_pending){b->handover_pending=false;ble_peer_t *p=&b->peer[b->selected];b->output=p->latest;b->output.upload_generation=b->output_epoch;}
}
void bp_snapshot(ble_peer_bank_t *b,unsigned slot,ble_node_snapshot_t *o){
 memset(o,0,sizeof(*o));if(slot>=BP_COUNT)return;ble_peer_t *p=&b->peer[slot];o->address_type=p->address_type;memcpy(o->address,p->address,6);o->phase=p->phase;o->conn_handle=p->handle;o->token=p->token;o->selected=b->output_valid && b->selected==(int)slot;o->last_good_us=p->good_us;o->upload_generation=o->selected?b->output_epoch:0;o->latest=p->latest;
}
