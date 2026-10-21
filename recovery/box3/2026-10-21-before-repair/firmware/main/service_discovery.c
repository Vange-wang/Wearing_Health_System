#include "service_discovery.h"
#include "service_origin.h"
#include "discovery_hint.h"
#include "discovery_protocol.h"
#include "device_auth_client.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "lwip/sockets.h"
#include <fcntl.h>
#include <string.h>
#include <errno.h>
static struct {
    int fd;uint32_t network;bool up,active,reserved;
    uint8_t nonce[16],tx[58],rx[83];
    unsigned sent,failures;int64_t began,next_send,next_cycle;
    uint8_t accepted_ip[4],accepted_instance[16];int64_t accepted_expires;
    void (*notify)(void);
    struct {
        uint32_t socket_ok,socket_fail,setup_fail,bind_ok,bind_fail,netif_fail;
        uint32_t send_calls,send_error,rx,rx82,recv_error,pending_reject,verify_ok,verify_reject,reserve_ok,reserve_reject;
        uint32_t cycles_failed,cycles_ok,begin_reject;
        int send_bytes,rx_len,last_errno;unsigned first_target;bool auth_ready;int64_t next_log;
    } diag;
} d={.fd=-1};
static void increment(uint32_t *value){if(*value<UINT32_MAX)(*value)++;}
static void diagnostic(int64_t now)
{
    if(now<d.diag.next_log)return;
    d.diag.next_log=now+10000000;
    ESP_LOGI("discovery","diag auth=%u sock_ok=%u sock_fail=%u setup_fail=%u bind_ok=%u bind_fail=%u netif_fail=%u sends=%u send_bytes=%d send_error=%u errno=%d first_target=%u",
        (unsigned)d.diag.auth_ready,(unsigned)d.diag.socket_ok,(unsigned)d.diag.socket_fail,(unsigned)d.diag.setup_fail,
        (unsigned)d.diag.bind_ok,(unsigned)d.diag.bind_fail,(unsigned)d.diag.netif_fail,(unsigned)d.diag.send_calls,
        d.diag.send_bytes,(unsigned)d.diag.send_error,d.diag.last_errno,d.diag.first_target);
    ESP_LOGI("discovery","diag rx=%u rx_len=%d rx82=%u recv_error=%u pending_reject=%u verify_ok=%u verify_reject=%u reserve_ok=%u reserve_reject=%u cycle_fail=%u cycle_ok=%u begin_reject=%u",
        (unsigned)d.diag.rx,d.diag.rx_len,(unsigned)d.diag.rx82,(unsigned)d.diag.recv_error,(unsigned)d.diag.pending_reject,
        (unsigned)d.diag.verify_ok,(unsigned)d.diag.verify_reject,(unsigned)d.diag.reserve_ok,(unsigned)d.diag.reserve_reject,
        (unsigned)d.diag.cycles_failed,(unsigned)d.diag.cycles_ok,(unsigned)d.diag.begin_reject);
}
static void close_socket(void){if(d.fd>=0)close(d.fd);d.fd=-1;d.active=false;d.reserved=false;}
void service_discovery_init(void (*notify)(void)){d.notify=notify;}
static uint32_t backoff(void){static const uint32_t delays[]={5,10,20,30};unsigned n=d.failures?d.failures-1:0;return delays[n<4?n:3];}
static void failed(int64_t now)
{
    d.active=false;d.reserved=false;if(d.failures<4)d.failures++;
    d.next_cycle=now+(int64_t)backoff()*1000000;
    increment(&d.diag.cycles_failed);diagnostic(now);
}
void service_discovery_poll(uint32_t generation,bool up)
{
    int64_t now=esp_timer_get_time();
    if(d.network!=generation || d.up!=up){
        close_socket();d.network=generation;d.up=up;d.failures=0;d.next_cycle=now;
        service_origin_network(generation,up);
        discovery_hint_network(generation,false,NULL,NULL);
    }
    d.diag.auth_ready=device_auth_discovery_ready();
    if(!up || !d.diag.auth_ready){diagnostic(now);return;}
    esp_netif_t *netif=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");esp_netif_ip_info_t info;
    if(!netif || esp_netif_get_ip_info(netif,&info)!=ESP_OK){increment(&d.diag.netif_fail);diagnostic(now);return;}
    discovery_hint_network(generation,true,(const uint8_t *)&info.ip.addr,(const uint8_t *)&info.netmask.addr);
    if(d.fd<0){
        d.fd=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
        if(d.fd<0){d.diag.last_errno=errno;increment(&d.diag.socket_fail);failed(now);return;}
        increment(&d.diag.socket_ok);
        int enabled=1;
        struct sockaddr_in local={.sin_family=AF_INET,.sin_port=0,.sin_addr.s_addr=info.ip.addr};
        if(setsockopt(d.fd,SOL_SOCKET,SO_BROADCAST,&enabled,sizeof(enabled)) ||
           fcntl(d.fd,F_SETFL,O_NONBLOCK)<0){d.diag.last_errno=errno;increment(&d.diag.setup_fail);close_socket();failed(now);return;}
        if(bind(d.fd,(struct sockaddr *)&local,sizeof(local))<0){
            d.diag.last_errno=errno;increment(&d.diag.bind_fail);close_socket();failed(now);return;
        }
        increment(&d.diag.bind_ok);
    }
    service_origin_expire_transaction(now);
    if(d.active && now-d.began>=4000000){
        service_origin_snapshot_t committed;
        if(d.reserved && service_origin_acquire(&committed,false) && committed.expires_us>=d.accepted_expires &&
            !memcmp(committed.ipv4,d.accepted_ip,4) && !memcmp(committed.instance,d.accepted_instance,16)){
            d.active=false;d.reserved=false;d.failures=0;d.next_cycle=d.began+60000000;
            increment(&d.diag.cycles_ok);
        }
        else failed(now);
    }
    if(!d.active && now>=d.next_cycle){
        esp_fill_random(d.nonce,16);
        if(service_origin_begin(d.nonce,generation,now) && paired_discovery_request(d.nonce,d.tx)){
            d.active=true;d.reserved=false;d.sent=0;d.began=now;d.next_send=now;
        }else{increment(&d.diag.begin_reject);failed(now);return;}
    }
    if(d.active && !d.reserved && d.sent<3 && now>=d.next_send){
        struct sockaddr_in dest={.sin_family=AF_INET,.sin_port=htons(8711)};
        dest.sin_addr.s_addr=info.ip.addr|~info.netmask.addr;
        if(d.sent==0){
            service_origin_snapshot_t active;
            d.diag.first_target=0;
            if(service_origin_acquire(&active,false)){
                memcpy(&dest.sin_addr.s_addr,active.ipv4,4);d.diag.first_target=1;
            }else{
                uint8_t target[4];
                unsigned selected=discovery_hint_target((const uint8_t *)&info.ip.addr,(const uint8_t *)&info.netmask.addr,target);
                if(selected){memcpy(&dest.sin_addr.s_addr,target,4);d.diag.first_target=selected;}
            }
        }
        d.diag.send_bytes=sendto(d.fd,d.tx,sizeof(d.tx),0,(struct sockaddr *)&dest,sizeof(dest));
        increment(&d.diag.send_calls);
        if(d.diag.send_bytes!=(int)sizeof(d.tx)){
            if(d.diag.send_bytes<0)d.diag.last_errno=errno;
            increment(&d.diag.send_error);
        }
        d.sent++;d.next_send=d.began+(int64_t)d.sent*1000000;
    }
    for(unsigned i=0;i<4;i++){
        struct sockaddr_in source;socklen_t size=sizeof(source);
        int n=recvfrom(d.fd,d.rx,sizeof(d.rx),0,(struct sockaddr *)&source,&size);
        if(n<0){if(errno!=EAGAIN && errno!=EWOULDBLOCK){
            d.diag.last_errno=errno;increment(&d.diag.recv_error);close_socket();failed(now);
        }break;}
        increment(&d.diag.rx);d.diag.rx_len=n;
        if(n!=82 || source.sin_family!=AF_INET)continue;
        increment(&d.diag.rx82);
        uint8_t nonce[16];uint32_t pending_generation;paired_discovery_reply_t reply;
        if(!service_origin_pending(nonce,&pending_generation,now) || pending_generation!=generation){increment(&d.diag.pending_reject);continue;}
        if(!paired_discovery_response(d.rx,(size_t)n,(const uint8_t *)&source.sin_addr.s_addr,ntohs(source.sin_port),nonce,
                (const uint8_t *)&info.ip.addr,(const uint8_t *)&info.netmask.addr,&reply)){
            increment(&d.diag.verify_reject);continue;
        }
        increment(&d.diag.verify_ok);
        if(service_origin_reserve(nonce,generation,reply.ipv4,reply.instance,reply.ttl,esp_timer_get_time())){
            increment(&d.diag.reserve_ok);
            d.reserved=true;memcpy(d.accepted_ip,reply.ipv4,4);memcpy(d.accepted_instance,reply.instance,16);
            d.accepted_expires=now+(int64_t)reply.ttl*1000000;
            if(d.notify)d.notify();
        }else increment(&d.diag.reserve_reject);
    }
    diagnostic(now);
}
uint32_t service_discovery_wait_ms(void)
{
    if(!d.up)return 1000;
    if(d.active)return 100;
    int64_t left=d.next_cycle-esp_timer_get_time();
    return left<=0?1:(left>60000000?60000:(uint32_t)((left+999)/1000));
}
