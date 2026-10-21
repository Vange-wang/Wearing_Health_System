#include "discovery_hint.h"
#include "nvs.h"
#include "esp_timer.h"
#include "esp_log.h"
#include <string.h>
#include "freertos/FreeRTOS.h"

#define HINT_NS "vb_disc_hint"
#define HINT_KEY "last_ready"
#define HINT_BYTES 16
static portMUX_TYPE hint_mux=portMUX_INITIALIZER_UNLOCKED;
#define LOCK() portENTER_CRITICAL(&hint_mux)
#define UNLOCK() portEXIT_CRITICAL(&hint_mux)
static struct {
    bool initialized,stored_valid,ram_valid,network_valid;
    uint32_t generation;
    uint8_t local[4],mask[4],stored[HINT_BYTES],ram[HINT_BYTES];
} h;
static uint32_t number(const uint8_t p[4])
{return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
static bool valid_mask(const uint8_t mask[4])
{
    uint32_t m=number(mask),host=~m;
    return m && host>=3 && (host&(host+1))==0;
}
static bool peer(const uint8_t ip[4],const uint8_t local[4],const uint8_t mask[4])
{
    if(!ip || !local || !mask || !valid_mask(mask))return false;
    uint32_t addr=number(ip),own=number(local),m=number(mask),net=own&m;
    return ip[0] && ip[0]!=127 && !(ip[0]==169 && ip[1]==254) && ip[0]<224 &&
        (addr&m)==net && addr!=own && addr!=net && addr!=(net|~m);
}
static bool valid_record(const uint8_t r[HINT_BYTES])
{
    if(r[0]!=1 || r[1] || r[2] || r[3] || !valid_mask(r+12))return false;
    uint32_t ip=number(r+4),net=number(r+8),mask=number(r+12);
    return (net&mask)==net && (ip&mask)==net && ip!=net && ip!=(net|~mask) &&
        r[4] && r[4]!=127 && !(r[4]==169 && r[5]==254) && r[4]<224;
}
static bool usable(const uint8_t r[HINT_BYTES],const uint8_t local[4],const uint8_t mask[4])
{
    if(!valid_record(r) || !peer(r+4,local,mask) || memcmp(r+12,mask,4))return false;
    for(unsigned i=0;i<4;i++)if(r[8+i]!=(uint8_t)(local[i]&mask[i]))return false;
    return true;
}
void discovery_hint_init(void)
{
    if(h.initialized)return;
    h.initialized=true;
    int64_t began=esp_timer_get_time();nvs_handle_t handle;uint8_t record[HINT_BYTES];size_t size=sizeof(record);
    esp_err_t open_rc=nvs_open(HINT_NS,NVS_READONLY,&handle),read_rc=ESP_ERR_NVS_NOT_FOUND;
    unsigned state=0;
    if(open_rc==ESP_OK){
        read_rc=nvs_get_blob(handle,HINT_KEY,record,&size);nvs_close(handle);
        if(read_rc==ESP_OK){
            if(size==sizeof(record) && valid_record(record)){
                memcpy(h.stored,record,sizeof(record));h.stored_valid=true;state=1;
            }else state=2;
        }else if(read_rc!=ESP_ERR_NVS_NOT_FOUND)state=3;
    }else if(open_rc!=ESP_ERR_NVS_NOT_FOUND)state=3;
    ESP_LOGI("discovery_hint","read state=%u open_rc=%ld read_rc=%ld elapsed_us=%lld",state,
        (long)open_rc,(long)read_rc,(long long)(esp_timer_get_time()-began));
}
void discovery_hint_network(uint32_t generation,bool up,const uint8_t local[4],const uint8_t mask[4])
{
    LOCK();
    if(generation!=h.generation || !up){h.network_valid=false;}
    h.generation=generation;
    if(up && local && mask && valid_mask(mask)){
        memcpy(h.local,local,4);memcpy(h.mask,mask,4);h.network_valid=true;
    }else h.network_valid=false;
    UNLOCK();
}
unsigned discovery_hint_target(const uint8_t local[4],const uint8_t mask[4],uint8_t target[4])
{
    if(!local || !mask || !target)return 0;
    LOCK();unsigned selected=0;
    if(h.ram_valid && usable(h.ram,local,mask)){memcpy(target,h.ram+4,4);selected=2;}
    else if(h.stored_valid && usable(h.stored,local,mask)){memcpy(target,h.stored+4,4);selected=2;}
    UNLOCK();return selected;
}
void discovery_hint_note_ready(const service_origin_snapshot_t *origin)
{
    service_origin_snapshot_t ready;
    if(!origin || !service_origin_acquire(&ready,true) || ready.epoch!=origin->epoch ||
       ready.wifi_generation!=origin->wifi_generation || ready.port!=origin->port ||
       memcmp(ready.ipv4,origin->ipv4,4) || memcmp(ready.instance,origin->instance,16))return;
    LOCK();
    if(h.network_valid && h.generation==ready.wifi_generation && peer(ready.ipv4,h.local,h.mask)){
        uint8_t record[HINT_BYTES]={1};
        memcpy(record+4,ready.ipv4,4);memcpy(record+12,h.mask,4);
        for(unsigned i=0;i<4;i++)record[8+i]=h.local[i]&h.mask[i];
        memcpy(h.ram,record,sizeof(record));h.ram_valid=true;
    }
    UNLOCK();
}
