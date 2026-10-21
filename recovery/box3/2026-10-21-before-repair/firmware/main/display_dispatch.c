#include "display_dispatch.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
static portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;
static const char *desired_path;
static uint32_t desired_command, emoji_seq, visual_seq, emoji_done, visual_done, ticks;
static uint32_t emoji_failed,visual_failed,emoji_retry,visual_retry;
static bool (*apply_emoji)(const char *);
static bool (*apply_visual)(uint32_t);
extern void display_diag_port(uint32_t *submit,uint32_t *done,uint32_t *errors);
extern void display_diag_png(uint32_t *info_in,uint32_t *info_out,uint32_t *decode_in,uint32_t *decode_out);
void display_dispatch_emoji(const char *path) {
    portENTER_CRITICAL(&mux);desired_path=path;++emoji_seq;portEXIT_CRITICAL(&mux);
}
void display_dispatch_visual(uint32_t command) {
    portENTER_CRITICAL(&mux);desired_command=command;++visual_seq;portEXIT_CRITICAL(&mux);
}
static void tick(lv_timer_t *timer) {
    (void)timer;
    portENTER_CRITICAL(&mux);
    ++ticks;uint32_t es=emoji_seq,vs=visual_seq,cmd=desired_command;
    const char *path=desired_path;
    bool ep=es!=emoji_done,vp=vs!=visual_done;
    portEXIT_CRITICAL(&mux);
    /* Called only by the existing internal-stack LVGL thread. */
    uint32_t now=lv_tick_get();
    if(vp && (vs!=visual_failed || (int32_t)(now-visual_retry)>=0)) {
        if(apply_visual(cmd)) {portENTER_CRITICAL(&mux);visual_done=vs;portEXIT_CRITICAL(&mux);}
        else {visual_failed=vs;visual_retry=now+1000;}
    }
    if(ep && (es!=emoji_failed || (int32_t)(now-emoji_retry)>=0)) {
        if(apply_emoji(path)) {portENTER_CRITICAL(&mux);emoji_done=es;portEXIT_CRITICAL(&mux);}
        else {emoji_failed=es;emoji_retry=now+1000;}
    }
}
bool display_dispatch_init(bool (*emoji)(const char *),bool (*visual)(uint32_t)) {
    apply_emoji=emoji;apply_visual=visual;
    return lv_timer_create(tick,20,NULL)!=NULL;
}
extern void voice_dns_diag_dump(void);
extern void voice_dns_net_snapshot(void);
void display_dispatch_heartbeat(void *unused) {
    (void)unused;
    for(;;) {
        uint32_t s,d,e,pi,po,di,do_,t,er,ea,vr,va;
        portENTER_CRITICAL(&mux);
        t=ticks;er=emoji_seq;ea=emoji_done;vr=visual_seq;va=visual_done;
        portEXIT_CRITICAL(&mux);
        display_diag_port(&s,&d,&e);display_diag_png(&pi,&po,&di,&do_);
        ESP_LOGI("display_diag","tick=%lu er=%lu ea=%lu vr=%lu va=%lu submit=%lu done=%lu errors=%lu pi=%lu po=%lu di=%lu dout=%lu free=%u largest=%u",
            (unsigned long)t,(unsigned long)er,(unsigned long)ea,(unsigned long)vr,(unsigned long)va,
            (unsigned long)s,(unsigned long)d,(unsigned long)e,(unsigned long)pi,(unsigned long)po,(unsigned long)di,(unsigned long)do_,
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
            (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
        voice_dns_diag_dump();
        voice_dns_net_snapshot();
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
