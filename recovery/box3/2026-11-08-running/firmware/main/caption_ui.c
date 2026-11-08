#include "caption_ui.h"
#include "caption_text.h"
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "bsp/esp-bsp.h"
#include "lvgl.h"
#include "esp_log.h"
#include "wake_engine.h"

LV_FONT_DECLARE(box_caption_font);
#define BODY_CAPACITY 32768U
#define VIEW_CAPACITY 800U
#define LINE_CAPACITY 160U
static portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;
static char *body;
static lv_obj_t *label;
static bool layout_supported=true;
static struct {
    uint32_t generation, epoch, applied_epoch;
    size_t read, used, high_water;
    bool finished, unavailable, desired_expanded, applied_expanded;
} state;
_Static_assert(sizeof(state)<=512, "caption control budget");
/* UI-worker-owned; never touched by the receiver or the LVGL layout callback. */
static char rows[5][LINE_CAPACITY], scratch[VIEW_CAPACITY];
static unsigned row_count;
static uint32_t view_epoch;
static TickType_t scroll_at;

static unsigned glyph_width(uint32_t cp,void *unused)
{
    (void)unused;lv_font_glyph_dsc_t d;
    if(!lv_font_get_glyph_dsc(&box_caption_font,&d,cp,0))return 0;
    if(d.is_placeholder || (d.adv_w!=8 && d.adv_w!=16) || d.ofs_x<0 ||
       d.box_w+d.ofs_x>d.adv_w || d.box_h>20)return 0;
    return d.adv_w;
}

static bool matches(uint32_t gen,uint32_t epoch)
{
    portENTER_CRITICAL(&mux);
    bool valid=gen && state.generation==gen && state.epoch==epoch;
    portEXIT_CRITICAL(&mux);
    return valid && wake_engine_generation()==gen;
}

void caption_ui_init(void)
{
    if(!body)body=malloc(BODY_CAPACITY);
    label=lv_label_create(lv_scr_act());
    lv_obj_set_style_text_font(label,&box_caption_font,0);
    lv_obj_set_style_text_line_space(label,8,0);
    lv_obj_set_style_text_align(label,LV_TEXT_ALIGN_CENTER,0);
    lv_obj_set_style_pad_all(label,0,0);
    lv_obj_set_style_border_width(label,0,0);
    lv_label_set_long_mode(label,LV_LABEL_LONG_CLIP);
    lv_obj_set_size(label,296,100);lv_obj_set_pos(label,12,128);
    lv_label_set_text(label,"");
}

void caption_ui_begin(uint32_t generation)
{
    portENTER_CRITICAL(&mux);
    state.generation=generation;++state.epoch;state.read=state.used=state.high_water=0;
    state.finished=false;state.unavailable=body==NULL || !layout_supported;state.desired_expanded=false;
    portEXIT_CRITICAL(&mux);
    if(!body)ESP_LOGW("caption","unavailable reason=body_allocation");
}

void caption_ui_cancel(uint32_t generation)
{
    portENTER_CRITICAL(&mux);
    if(state.generation==generation) {
        state.generation=0;++state.epoch;state.read=state.used=0;
        state.finished=false;state.desired_expanded=false;state.unavailable=false;
    }
    portEXIT_CRITICAL(&mux);
}

void caption_ui_finish(uint32_t generation)
{
    bool ended=false;size_t pending=0,peak=0;
    portENTER_CRITICAL(&mux);
    if(generation && state.generation==generation && !state.finished) {
        state.finished=true;ended=true;pending=state.used;peak=state.high_water;
    }
    portEXIT_CRITICAL(&mux);
    if(ended)ESP_LOGI("caption","input_end generation=%u pending_bytes=%u high_water=%u",
                     (unsigned)generation,(unsigned)pending,(unsigned)peak);
}

bool caption_ui_submit(char *text,uint32_t generation)
{
    if(!text)return false;
    size_t length=strlen(text);bool accepted=false,overflow=false;
    if(!caption_text_valid(text,length)){free(text);return false;}
    portENTER_CRITICAL(&mux);
    if(body && generation && state.generation==generation && !state.finished && !state.unavailable) {
        if(length<=512 && length<=BODY_CAPACITY-state.used) {
            size_t end=(state.read+state.used)%BODY_CAPACITY;
            size_t first=BODY_CAPACITY-end;if(first>length)first=length;
            memcpy(body+end,text,first);memcpy(body,text+first,length-first);
            state.used+=length;if(state.used>state.high_water)state.high_water=state.used;
            accepted=true;
        } else {
            state.unavailable=true;state.read=state.used=0;
            ++state.epoch; /* Invalidate every in-flight body/layout snapshot. */
            overflow=true;
        }
    }
    portEXIT_CRITICAL(&mux);
    free(text);
    if(overflow)ESP_LOGW("caption","unavailable reason=capacity generation=%u capacity=%u",(unsigned)generation,BODY_CAPACITY);
    return accepted;
}

bool caption_ui_layout_expanded(void)
{
    portENTER_CRITICAL(&mux);bool value=state.applied_expanded;portEXIT_CRITICAL(&mux);
    return value;
}

void caption_ui_apply_layout(void (*place_emoji)(bool),int width,int height)
{
    if(width!=320||height!=240) {
        portENTER_CRITICAL(&mux);
        layout_supported=false;
        if(!state.unavailable)++state.epoch;
        state.unavailable=true;
        portEXIT_CRITICAL(&mux);
        return;
    }
    portENTER_CRITICAL(&mux);
    uint32_t epoch=state.epoch;
    bool expanded=state.generation && state.desired_expanded;
    bool changed=epoch!=state.applied_epoch || expanded!=state.applied_expanded;
    portEXIT_CRITICAL(&mux);
    if(!changed)return;
    /* LVGL owner applies both objects together. Epoch acknowledgement, not the
     * previous mode bit, authorizes the worker to fill a new turn's viewport. */
    if(place_emoji)place_emoji(expanded);
    if(label) {
        lv_obj_set_size(label,expanded?304:296,expanded?148:100);
        lv_obj_set_pos(label,expanded?8:12,expanded?88:128);
    }
    portENTER_CRITICAL(&mux);
    state.applied_expanded=expanded; /* Actual geometry, even for a stale request. */
    bool current=state.epoch==epoch &&
        expanded==(state.generation && state.desired_expanded);
    if(current)state.applied_epoch=epoch;
    portEXIT_CRITICAL(&mux);
    /* A begin racing the LVGL callback cannot expose new content in old geometry.
     * The next timer reconciles the latest request; the audio path never waits. */
    if(!current && label)lv_label_set_text(label,"");
}

static TickType_t reading_time(const char *line)
{
    unsigned words=0,cjk=0;bool word=false;
    for(const unsigned char *s=(const unsigned char *)line;*s;s++) {
        if(*s>=0xe0 && *s<0xf0){cjk++;word=false;}
        else if(*s<128) {
            if(*s==' '||*s=='\t'||*s=='>')word=false;
            else if(!word){words++;word=true;}
        }
    }
    unsigned ms=words*250+cjk*200;if(ms<800)ms=800;
    return pdMS_TO_TICKS(ms);
}

static void caption_ui_step(void)
{
    /* No reading-clock/cursor changes before a successful nonblocking UI lock.
     * The receiver never takes this lock. Work remains at most five lines. */
    if(!bsp_display_lock(1))return;
    uint32_t gen,epoch;bool unavailable,expanded,layout_ready;size_t read;
    portENTER_CRITICAL(&mux);
    gen=state.generation;epoch=state.epoch;
    portEXIT_CRITICAL(&mux);
    if(gen && wake_engine_generation()!=gen) {
        caption_ui_cancel(gen);
        portENTER_CRITICAL(&mux);gen=state.generation;epoch=state.epoch;portEXIT_CRITICAL(&mux);
    }
    if(epoch!=view_epoch) {
        row_count=0;scroll_at=0;memset(rows,0,sizeof(rows));view_epoch=epoch;
    }
    portENTER_CRITICAL(&mux);
    unavailable=state.unavailable;expanded=state.applied_expanded;
    layout_ready=state.applied_epoch==epoch;read=state.read;
    portEXIT_CRITICAL(&mux);
    if(gen && !unavailable && !layout_ready) {
        if(label && lv_label_get_text(label)[0])lv_label_set_text(label,"");
        bsp_display_unlock();return;
    }
    /* Tentative rows live on the existing UI task stack. The ring and committed
     * rows remain recoverable until label update AND same-version validation. */
    char proposed[5][LINE_CAPACITY];memcpy(proposed,rows,sizeof(proposed));
    unsigned count=row_count,max_rows=expanded?5:3;
    size_t consumed=0;
    bool reset_clock=scroll_at==0,valid=true;
    TickType_t now=xTaskGetTickCount();
    if(gen && !unavailable) {
        for(unsigned work=0;work<5;work++) {
            portENTER_CRITICAL(&mux);
            valid=state.epoch==epoch && !state.unavailable && state.read==read &&
                state.applied_epoch==epoch && consumed<=state.used;
            if(!valid){portEXIT_CRITICAL(&mux);break;}
            size_t remaining=state.used-consumed;
            bool finished=state.finished;
            size_t n=remaining;if(n>=sizeof(scratch))n=sizeof(scratch)-1;
            for(size_t i=0;i<n;i++)scratch[i]=body[(read+consumed+i)%BODY_CAPACITY];
            portEXIT_CRITICAL(&mux);
            while(n && !caption_text_valid(scratch,n))n--;
            scratch[n]=0;
            if(!n)break;
            char line[LINE_CAPACITY];caption_line_t result;
            if(!caption_text_line(scratch,n,finished&&n==remaining,expanded?304:296,
                                  glyph_width,NULL,line,sizeof(line),&result)) {
                portENTER_CRITICAL(&mux);
                if(state.epoch==epoch){state.unavailable=true;++state.epoch;}
                portEXIT_CRITICAL(&mux);valid=false;break;
            }
            /* Never index rows outside either the physical array or confirmed
             * viewport. Epoch gating makes same-turn shrink unreachable. */
            if(count>max_rows || count>5){valid=false;break;}
            if(count>=max_rows) {
                if(!expanded) {
                    portENTER_CRITICAL(&mux);
                    if(state.epoch==epoch && !state.unavailable)state.desired_expanded=true;
                    portEXIT_CRITICAL(&mux);break;
                }
                if(!result.ready && !line[0])break;
                if(reset_clock || (int32_t)(now-scroll_at)<0)break;
                memmove(proposed,proposed+1,(max_rows-1)*LINE_CAPACITY);count--;
                proposed[count][0]=0;reset_clock=true;
            }
            if(count>=5){valid=false;break;}
            memcpy(proposed[count],line,strlen(line)+1);
            if(!result.ready)break;
            if(result.consumed>remaining){valid=false;break;}
            consumed+=result.consumed;count++;
        }
    }
    size_t size=0;
    if(unavailable) {
        const char *message="[caption unavailable]";memcpy(scratch,message,strlen(message)+1);
    } else {
        unsigned shown=count;
        if(shown<max_rows && shown<5 && proposed[shown][0])shown++;
        if(shown>max_rows || shown>5)valid=false;
        for(unsigned i=0;valid && i<shown;i++) {
            size_t n=strlen(proposed[i]);if(size+n+2>sizeof(scratch)){valid=false;break;}
            if(i)scratch[size++]='\n';
            memcpy(scratch+size,proposed[i],n);size+=n;
        }
        scratch[size]=0;
    }
    valid=valid && matches(gen,epoch);
    const char *next=valid?scratch:"";
    if(label && strcmp(lv_label_get_text(label),next)!=0)lv_label_set_text(label,next);
    bool painted=label && strcmp(lv_label_get_text(label),next)==0;
    if(valid && painted && !unavailable) {
        portENTER_CRITICAL(&mux);
        valid=state.epoch==epoch && state.generation==gen && !state.unavailable &&
            state.applied_epoch==epoch && state.applied_expanded==expanded &&
            state.read==read && consumed<=state.used;
        if(valid){state.read=(read+consumed)%BODY_CAPACITY;state.used-=consumed;}
        portEXIT_CRITICAL(&mux);
        if(valid) {
            memcpy(rows,proposed,sizeof(rows));row_count=count;
            if(reset_clock && (count || proposed[0][0]))
                scroll_at=xTaskGetTickCount()+reading_time(rows[0]);
        }
    }
    /* Overflow/cancel may occur during font measurement or the LVGL setter.
     * Surface the CURRENT failure rather than leaving stale text on screen. */
    if(!matches(gen,epoch)) {
        portENTER_CRITICAL(&mux);
        bool failed=state.generation==gen && gen && state.unavailable;
        portEXIT_CRITICAL(&mux);
        const char *current=failed?"[caption unavailable]":"";
        if(label && strcmp(lv_label_get_text(label),current)!=0)lv_label_set_text(label,current);
    }
    bsp_display_unlock();
}

void caption_ui_task(void *unused)
{
    (void)unused;
    while(true){caption_ui_step();vTaskDelay(pdMS_TO_TICKS(50));}
}
#ifdef CAPTION_UI_HOST_TEST
void caption_ui_test_step(void){caption_ui_step();}
size_t caption_ui_test_metric(int k){
    return k==0?state.used:k==1?state.high_water:k==2?state.epoch:k==3?state.unavailable:sizeof(state)+sizeof(rows)+sizeof(scratch)+BODY_CAPACITY;
}
#endif
