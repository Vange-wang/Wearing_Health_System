#include "voice_v2_transport.h"
#include "device_auth_client.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>


/* First numeric failure only. Never format payloads or touch transport state. */
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
static void vf_fail(voice_v2_transport_t *t,uint32_t stage,int32_t rc,int error_number,bool errno_valid)
{
    if(t->failure.valid)return;
    t->failure=(voice_v2_failure_t){.valid=1,.stage=stage,.rc=rc,.error_number=error_number,
        .errno_valid=errno_valid,.samples=t->samples,.last_progress_us=t->last_progress_us};
}
static int vf_esp(voice_v2_transport_t *t,uint32_t stage,int rc)
{if(rc!=ESP_OK)vf_fail(t,stage,rc,stage==5?0:errno,stage!=5);return rc;}
#define VF_FAIL(t,s,r,e,v) vf_fail((t),(s),(r),(e),(v))
#define VF_ESP(t,s,call) vf_esp((t),(s),(call))
#else
#define VF_FAIL(t,s,r,e,v) ((void)0)
#define VF_ESP(t,s,call) (call)
#endif

#define V2_POLL_MS 200
#define V2_IDLE_US 30000000LL
typedef struct { char data[512]; size_t used; bool overflow; } reply_t;
static esp_err_t collect(esp_http_client_event_t *e)
{
    reply_t *r=e->user_data;
    if(e->event_id==HTTP_EVENT_ON_DATA && r && e->data_len>0) {
        size_t n=(size_t)e->data_len;
        if(n>=sizeof(r->data)-r->used) {r->overflow=true;return ESP_FAIL;}
        memcpy(r->data+r->used,e->data,n);r->used+=n;r->data[r->used]=0;
    }
    return ESP_OK;
}
static bool headers(esp_http_client_handle_t c,const voice_v2_identity_t *id)
{
    if(esp_http_client_set_header(c,"X-Voice-Session",id->session)!=ESP_OK)return false;
    const char *keys[]={"X-Voice-Turn","X-Voice-Revision","X-Voice-Segment","X-Voice-Sample-Start"};
    uint32_t values[]={id->turn,id->revision,id->segment,id->sample_start};
    for(size_t i=0;i<4;i++){
        char value[16];snprintf(value,sizeof(value),"%lu",(unsigned long)values[i]);
        if(esp_http_client_set_header(c,keys[i],value)!=ESP_OK)return false;
    }
    return true;
}
static bool request(const service_origin_snapshot_t *origin,service_route_t route,const char *body,size_t length,
                    const voice_v2_identity_t *id,reply_t *reply)
{
    char url[96];
    if(!service_origin_can_request(origin) || !service_origin_url(origin,route,url,sizeof(url)))return false;
    esp_http_client_config_t cfg={.url=url,.method=body?HTTP_METHOD_POST:HTTP_METHOD_GET,
        .timeout_ms=2000,.event_handler=collect,.user_data=reply,.disable_auto_redirect=true};
    esp_http_client_handle_t c=esp_http_client_init(&cfg);
    if(!c)return false;
    bool ok=add_device_auth_header(c)==ESP_OK;
    if(ok && route==ORIGIN_SESSION)ok=service_origin_headers(c,origin);
    if(ok && id)ok=headers(c,id);
    if(ok && body)ok=esp_http_client_set_header(c,"Content-Type","application/json")==ESP_OK &&
        esp_http_client_set_post_field(c,body,(int)length)==ESP_OK;
    if(ok)ok=esp_http_client_perform(c)==ESP_OK && esp_http_client_get_status_code(c)==200 && !reply->overflow;
    esp_http_client_cleanup(c);
    return ok && service_origin_current(origin);
}
bool voice_v2_register_session(const service_origin_snapshot_t *origin,char session[33])
{
    reply_t reply={0};
    if(!request(origin,ORIGIN_SESSION,NULL,0,NULL,&reply))return false;
    cJSON *root=cJSON_ParseWithLength(reply.data,reply.used);
    const cJSON *item=root?cJSON_GetObjectItemCaseSensitive(root,"challenge"):NULL;
    char nonce[33]={0};
    bool ok=cJSON_IsString(item) && strlen(item->valuestring)==32;
    if(ok)memcpy(nonce,item->valuestring,32);
    cJSON_Delete(root);
    if(!ok)return false;
    uint8_t random[16];esp_fill_random(random,sizeof(random));
    static const char hex[]="0123456789abcdef";
    char fresh[33];
    for(size_t i=0;i<16;i++){fresh[i*2]=hex[random[i]>>4];fresh[i*2+1]=hex[random[i]&15];}
    fresh[32]=0;
    /* Challenge is server data; validate before embedding in a fixed JSON body. */
    for(size_t i=0;i<32;i++)if(!strchr(hex,nonce[i]))return false;
    char body[128];int n=snprintf(body,sizeof(body),"{\"session\":\"%s\",\"challenge\":\"%s\"}",fresh,nonce);
    memset(&reply,0,sizeof(reply));
    if(n<=0 || (size_t)n>=sizeof(body) || !request(origin,ORIGIN_SESSION,body,(size_t)n,NULL,&reply))return false;
    root=cJSON_ParseWithLength(reply.data,reply.used);item=root?cJSON_GetObjectItemCaseSensitive(root,"status"):NULL;
    ok=cJSON_IsString(item) && strcmp(item->valuestring,"registered")==0;
    item=root?cJSON_GetObjectItemCaseSensitive(root,"pc_instance"):NULL;
    char expected[33];
    for(unsigned i=0;i<16;i++){expected[2*i]=hex[origin->instance[i]>>4];expected[2*i+1]=hex[origin->instance[i]&15];}expected[32]=0;
    ok=ok && cJSON_IsString(item) && strcmp(item->valuestring,expected)==0 && service_origin_current(origin);
    cJSON_Delete(root);
    if(ok)memcpy(session,fresh,sizeof(fresh));
    return ok;
}
static bool cancelled(voice_v2_transport_t *t)
{return !t->client || !service_origin_current(&t->id.origin) || (t->cancelled && t->cancelled(t->user));}
static bool write_all(voice_v2_transport_t *t,const void *data,size_t n)
{
    const char *p=data;
    while(n){
        if(cancelled(t)){VF_FAIL(t,18,0,0,false);return false;}
        int wrote=esp_http_client_write(t->client,p,(int)n);
        if(wrote<=0 || (size_t)wrote>n){VF_FAIL(t,6,wrote,errno,wrote<0);return false;}
        p+=wrote;n-=(size_t)wrote;
    }
    return true;
}
static bool framed_chunk(voice_v2_transport_t *t,char kind,const void *data,size_t n)
{
    char chunk[20];int size=snprintf(chunk,sizeof(chunk),"%x\r\n",(unsigned)(n+5));
    uint8_t frame[5]={(uint8_t)kind,(uint8_t)(n>>24),(uint8_t)(n>>16),(uint8_t)(n>>8),(uint8_t)n};
    return size>0 && (size_t)size<sizeof(chunk) && write_all(t,chunk,(size_t)size) &&
        write_all(t,frame,sizeof(frame)) && write_all(t,data,n) && write_all(t,"\r\n",2);
}
bool voice_v2_open(voice_v2_transport_t *t,const voice_v2_identity_t *id,voice_v2_cancel_fn cancel,void *user,const char *prior_events)
{
    memset(t,0,sizeof(*t));t->id=*id;t->cancelled=cancel;t->user=user;
    /* The SDK cannot split one header across TX buffers. Keep first-turn default. */
    enum { PRIOR_EVENTS_MAX = 1024, PRIOR_HEADER_TX_SIZE = 1152 };
    _Static_assert(PRIOR_HEADER_TX_SIZE >= sizeof("X-Voice-Prior-Events")-1+2+PRIOR_EVENTS_MAX+2+3,
                   "TX buffer must fit a complete prior-events header plus SDK reserve");
    const bool has_prior=prior_events && *prior_events;
    if(has_prior && strnlen(prior_events,PRIOR_EVENTS_MAX+1)>PRIOR_EVENTS_MAX){VF_FAIL(t,3,0,0,false);return false;}
    char url[96];
    if(!service_origin_can_request(&id->origin) || !service_origin_url(&id->origin,ORIGIN_V2_STREAM,url,sizeof(url))){VF_FAIL(t,1,0,0,false);return false;}
    esp_http_client_config_t cfg={.url=url,.method=HTTP_METHOD_POST,
        .timeout_ms=2000,.buffer_size=8192,.buffer_size_tx=has_prior?PRIOR_HEADER_TX_SIZE:0,.disable_auto_redirect=true};
    t->client=esp_http_client_init(&cfg);
    if(!t->client){VF_FAIL(t,2,0,0,false);return false;}
    if(has_prior && VF_ESP(t,3,esp_http_client_set_header(t->client,"X-Voice-Prior-Events",prior_events))!=ESP_OK){voice_v2_close(t);return false;}
    if(!headers(t->client,id) || esp_http_client_set_header(t->client,"Content-Type","application/x-voice-v2")!=ESP_OK ||
       VF_ESP(t,4,open_authenticated_http(t->client,-1))!=ESP_OK){voice_v2_close(t);return false;}
    t->open=true;mbedtls_sha256_init(&t->sha);t->sha_ready=true;
    if(VF_ESP(t,5,mbedtls_sha256_starts(&t->sha,0))!=0){voice_v2_close(t);return false;}
    return true;
}
bool voice_v2_write_pcm(voice_v2_transport_t *t,const int16_t *pcm,size_t samples)
{
    if(!t->sha_ready || !samples || samples>8192 || samples>240000-t->samples){VF_FAIL(t,7,0,0,false);return false;}
    if(!framed_chunk(t,'P',pcm,samples*2) || VF_ESP(t,5,mbedtls_sha256_update(&t->sha,(const unsigned char *)pcm,samples*2))!=0)return false;
    t->samples+=(uint32_t)samples;return true;
}
bool voice_v2_end_input(voice_v2_transport_t *t,bool limit)
{
    if(!t->sha_ready || !t->samples || (limit && t->samples!=240000)){VF_FAIL(t,8,0,0,false);return false;}
    uint8_t digest[32];char hex[65];static const char digits[]="0123456789abcdef";
    if(VF_ESP(t,5,mbedtls_sha256_finish(&t->sha,digest))!=0)return false;
    mbedtls_sha256_free(&t->sha);t->sha_ready=false;
    for(size_t i=0;i<32;i++){hex[2*i]=digits[digest[i]>>4];hex[2*i+1]=digits[digest[i]&15];}hex[64]=0;
    memcpy(t->digest,hex,sizeof(hex));
    char body[160];int n=snprintf(body,sizeof(body),"{\"reason\":\"%s\",\"samples\":%lu,\"sha256\":\"%s\"}",
        limit?"segment_limit":"soft_endpoint",(unsigned long)t->samples,hex);
    if(n<=0 || (size_t)n>=sizeof(body) || !framed_chunk(t,'E',body,(size_t)n) || !write_all(t,"0\r\n\r\n",5))return false;
    t->last_progress_us=esp_timer_get_time();
    return VF_ESP(t,10,esp_http_client_set_timeout_ms(t->client,V2_POLL_MS))==ESP_OK;
}
bool voice_v2_commit_boundary(voice_v2_transport_t *t)
{
    if(t->samples!=240000 || !t->digest[0] || !service_origin_can_request(&t->id.origin))return false;
    if(t->client){esp_http_client_close(t->client);esp_http_client_cleanup(t->client);t->client=NULL;}
    char body[128];int n=snprintf(body,sizeof(body),"{\"samples\":%lu,\"sha256\":\"%s\"}",
        (unsigned long)t->samples,t->digest);
    if(n<=0 || (size_t)n>=sizeof(body))return false;
    char url[96];if(!service_origin_url(&t->id.origin,ORIGIN_COMMIT,url,sizeof(url)))return false;
    esp_http_client_config_t cfg={.url=url,.method=HTTP_METHOD_POST,
        .timeout_ms=2000,.buffer_size=8192,.disable_auto_redirect=true};
    t->client=esp_http_client_init(&cfg);
    if(!t->client || !headers(t->client,&t->id) ||
       esp_http_client_set_header(t->client,"Content-Type","application/json")!=ESP_OK ||
       VF_ESP(t,4,open_authenticated_http(t->client,n))!=ESP_OK || !write_all(t,body,(size_t)n))return false;
    t->open=true;t->last_progress_us=esp_timer_get_time();
    return VF_ESP(t,10,esp_http_client_set_timeout_ms(t->client,V2_POLL_MS))==ESP_OK;
}
int voice_v2_fetch_status(voice_v2_transport_t *t)
{
    while(!cancelled(t) && esp_timer_get_time()-t->last_progress_us<V2_IDLE_US){
        int64_t n=esp_http_client_fetch_headers(t->client);
        if(n>=0){t->last_progress_us=esp_timer_get_time();
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
            int status=esp_http_client_get_status_code(t->client);if(status!=200)VF_FAIL(t,12,status,0,false);return status;
#else
            return esp_http_client_get_status_code(t->client);
#endif
        }
        if(n!=-ESP_ERR_HTTP_EAGAIN && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=ETIMEDOUT){VF_FAIL(t,11,(int32_t)n,errno,true);return -1;}
        vTaskDelay(1);
    }
    VF_FAIL(t,13,-1,0,false);return -1;
}
bool voice_v2_read_exact(voice_v2_transport_t *t,void *data,size_t length)
{
    char *p=data;
    while(length && !cancelled(t)){
        int n=esp_http_client_read(t->client,p,(int)length);
        if(n>0){p+=n;length-=(size_t)n;t->last_progress_us=esp_timer_get_time();continue;}
        if(esp_http_client_is_complete_data_received(t->client)){VF_FAIL(t,14,n,errno,n<0);return false;}
        if(esp_timer_get_time()-t->last_progress_us>=V2_IDLE_US){VF_FAIL(t,15,n,0,false);return false;}
        if(n<0 && n!=-ESP_ERR_HTTP_EAGAIN && errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=ETIMEDOUT){VF_FAIL(t,16,n,errno,true);return false;}
        vTaskDelay(1);
    }
    if(length!=0)VF_FAIL(t,17,0,0,false);
    return length==0 && !cancelled(t);
}
bool voice_v2_event(const voice_v2_identity_t *id,const char *json,size_t length)
{
    reply_t reply={0};
    if(!json || !length || length>512 || !request(&id->origin,ORIGIN_EVENTS,json,length,id,&reply))return false;
    cJSON *root=cJSON_ParseWithLength(reply.data,reply.used);
    const cJSON *status=root?cJSON_GetObjectItemCaseSensitive(root,"status"):NULL;
    bool ok=cJSON_IsString(status) && (!strcmp(status->valuestring,"accepted") || !strcmp(status->valuestring,"duplicate") || !strcmp(status->valuestring,"retired_receipt"));
    cJSON_Delete(root);return ok;
}
void voice_v2_close(voice_v2_transport_t *t)
{
    if(t->sha_ready)mbedtls_sha256_free(&t->sha);
    if(t->client){if(t->open)esp_http_client_close(t->client);esp_http_client_cleanup(t->client);}
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    voice_v2_failure_t failure=t->failure;failure.samples=t->samples;failure.last_progress_us=t->last_progress_us;
#endif
    memset(t,0,sizeof(*t));
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    t->failure=failure;
#endif
}
