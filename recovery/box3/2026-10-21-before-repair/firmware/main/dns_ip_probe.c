/* DIAGNOSTIC ONLY: no token, DNS, retry, redirects or endpoint fallback. */
#include "dns_ip_probe.h"
#include "audio_session.h"
#include "wake_engine.h"
#include "esp_timer.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "lwip/sockets.h"
#include "lwip/inet.h"
#include <errno.h>
#include <fcntl.h>
#include <string.h>
static uint32_t pending_generation;
static int64_t last_attempt;
void dns_ip_probe_request(uint32_t generation) {
    __atomic_store_n(&pending_generation,generation+1,__ATOMIC_RELEASE);
}
static bool idle(void) {
    return !audio_session_capture_active() && audio_session_owner_is(AUDIO_SESSION_OWNER_NONE)
        && wake_engine_state()==WAKE_ENGINE_STATE_IDLE;
}
static int probe_stop(int64_t deadline,uint32_t generation,uint32_t (*current_generation)(void)) {
    if(current_generation()!=generation)return 8;
    if(!idle())return 6;
    if(esp_timer_get_time()>=deadline)return 9;
    return 0;
}
void dns_ip_probe_poll(uint32_t (*current_generation)(void)) {
    uint32_t generation=current_generation();
    uint32_t requested=__atomic_load_n(&pending_generation,__ATOMIC_ACQUIRE);
    if(!requested || !idle())return;
    int64_t start=esp_timer_get_time();
    if(start-last_attempt<30000000)return;
    requested=__atomic_exchange_n(&pending_generation,0,__ATOMIC_ACQ_REL);
    if(requested!=generation+1)return;
    last_attempt=start;
    esp_netif_t *netif=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_ip_info_t ip={0};
    struct sockaddr_in dest={.sin_family=AF_INET,.sin_port=htons(8710)};
    inet_pton(AF_INET,"192.168.0.113",&dest.sin_addr);
    if(!netif || !esp_netif_is_netif_up(netif) || esp_netif_get_ip_info(netif,&ip)!=ESP_OK
       || !ip.ip.addr || !ip.netmask.addr
       || (ip.ip.addr & ip.netmask.addr)!=(dest.sin_addr.s_addr & ip.netmask.addr)) {
        ESP_LOGI("dns_ip_diag","stage=8 err=0 connected=0 status=0 elapsed_ms=0");return;
    }
    int fd=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP),stage=1,error=0,status=0,connected=0;
    if(fd<0){error=errno;goto done;}
    if(fcntl(fd,F_SETFL,O_NONBLOCK)<0){error=errno;goto done;}
    int stop=probe_stop(start+1000000,generation,current_generation);
    if(stop){stage=stop;goto done;}
    int result=connect(fd,(struct sockaddr *)&dest,sizeof(dest));
    if(result<0 && errno!=EINPROGRESS){error=errno;stage=2;goto done;}
    stage=2;
    const char request[]="GET /api/v1/health HTTP/1.1\r\nHost: 192.168.0.113:8710\r\nConnection: close\r\n\r\n";
    size_t sent=0,used=0;char response[128];
    while(true) {
        stop=probe_stop(start+1000000,generation,current_generation);
        if(stop){stage=stop;break;}
        fd_set reads,writes;FD_ZERO(&reads);FD_ZERO(&writes);
        if(stage==4)FD_SET(fd,&reads);else FD_SET(fd,&writes);
        int64_t remaining=start+1000000-esp_timer_get_time();
        if(remaining<=0){stage=9;break;}
        struct timeval wait={.tv_sec=0,.tv_usec=remaining<50000?(long)remaining:50000};
        int ready=select(fd+1,&reads,&writes,NULL,&wait);
        stop=probe_stop(start+1000000,generation,current_generation);
        if(stop){stage=stop;break;}
        if(ready<0){error=errno;break;}if(!ready)continue;
        if(stage==2){socklen_t length=sizeof(error);if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&length)<0){error=errno;break;}if(error)break;connected=1;stage=3;}
        stop=probe_stop(start+1000000,generation,current_generation);
        if(stop){stage=stop;break;}
        if(stage==3){
            int n=send(fd,request+sent,sizeof(request)-1-sent,0);
            if(n<0){if(errno==EWOULDBLOCK || errno==EAGAIN)continue;error=errno;break;}
            if(n==0)break;
            sent+=(size_t)n;
            if(sent==sizeof(request)-1)stage=4;
        }else if(stage==4){
            int n=recv(fd,response+used,sizeof(response)-used,0);
            stop=probe_stop(start+1000000,generation,current_generation);
            if(stop){stage=stop;status=0;break;}
            if(n<0){if(errno==EWOULDBLOCK || errno==EAGAIN)continue;error=errno;break;}
            if(n==0)break;
            used+=(size_t)n;
            if(used>=12){
                if(!memcmp(response,"HTTP/1.",7) && response[8]==' '
                   && response[9]>='1' && response[9]<='5' && response[10]>='0' && response[10]<='9'
                   && response[11]>='0' && response[11]<='9') {
                    status=(response[9]-'0')*100+(response[10]-'0')*10+response[11]-'0';stage=5;
                }
                break;
            }
        }
    }
done:
    if(fd>=0)close(fd);
    int completion_stop=probe_stop(start+1000000,generation,current_generation);
    if(completion_stop){stage=completion_stop;status=0;}
    ESP_LOGI("dns_ip_diag","stage=%d err=%d connected=%d status=%d elapsed_ms=%lu",stage,error,connected,status,
        (unsigned long)((esp_timer_get_time()-start)/1000));
}
