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
typedef struct caption_node {
    struct caption_node *next;
    char *text;
    uint32_t generation;
    size_t length;
} caption_node_t;
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static caption_node_t *head, *tail;
static uint32_t current_generation;
static lv_obj_t *label;
static bool worker_ready;

static bool generation_matches(uint32_t generation)
{
    portENTER_CRITICAL(&mux);
    bool matches=current_generation==generation;
    portEXIT_CRITICAL(&mux);
    return matches && generation!=0 && wake_engine_generation()==generation;
}

static void dispose(caption_node_t *node)
{
    while (node) {
        caption_node_t *next = node->next;
        free(node->text); free(node); node = next;
    }
}

void caption_ui_init(void)
{
    label = lv_label_create(lv_scr_act());
    lv_obj_set_size(label, 296, 100);
    lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, -12);
    lv_obj_set_style_text_font(label, &box_caption_font, 0);
    lv_obj_set_style_text_line_space(label, 8, 0);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
    lv_label_set_text(label, "");
}

void caption_ui_begin(uint32_t generation)
{
    portENTER_CRITICAL(&mux);
    caption_node_t *old = head;
    head = tail = NULL;
    current_generation = generation;
    portEXIT_CRITICAL(&mux);
    dispose(old);
}

void caption_ui_cancel(uint32_t generation)
{
    portENTER_CRITICAL(&mux);
    caption_node_t *old = NULL;
    if (current_generation == generation) {
        current_generation = 0;
        old = head; head = tail = NULL;
    }
    portEXIT_CRITICAL(&mux);
    dispose(old);
}

bool caption_ui_submit(char *text, uint32_t generation)
{
    caption_node_t *node = malloc(sizeof(*node));
    if (node == NULL) {
        free(text); ESP_LOGW("caption", "unavailable reason=no_memory"); return false;
    }
    *node = (caption_node_t){.text=text,.generation=generation,.length=strlen(text)};
    portENTER_CRITICAL(&mux);
    bool accepted = worker_ready && generation != 0 && current_generation == generation;
    if (accepted) {
        if (tail) tail->next = node; else head = node;
        tail = node;
    }
    portEXIT_CRITICAL(&mux);
    if (!accepted) dispose(node);
    return accepted;
}

static caption_node_t *active = NULL;
static size_t offset = 0;
static uint32_t shown_generation = 0;
static TickType_t next_page = 0;

static void caption_ui_step(void)
{
        portENTER_CRITICAL(&mux);
        uint32_t generation = current_generation;
        portEXIT_CRITICAL(&mux);
        if (generation && wake_engine_generation() != generation) {
            caption_ui_cancel(generation); generation = 0;
        }
        if (active && active->generation != generation) { dispose(active); active=NULL; }
        if (shown_generation != generation) {
            if (!bsp_display_lock(1)) { return; }
            if (label) lv_label_set_text(label, "");
            bsp_display_unlock(); shown_generation=generation; next_page=0;
        }
        if (active == NULL) {
            portENTER_CRITICAL(&mux);
            active=head;
            if (active) { head=active->next; active->next=NULL; if (!head) tail=NULL; }
            portEXIT_CRITICAL(&mux);
            offset=0;
        }
        TickType_t now=xTaskGetTickCount();
        if (active && (next_page == 0 || (int32_t)(now-next_page)>=0)) {
            /* Three 18-glyph lines are a viewport, not a response length cap. */
            char page[3*18*4+3+1]; size_t cursor=offset;
            if (!caption_text_page(active->text,active->length,&cursor,page,sizeof(page))) {
                ESP_LOGW("caption","unavailable reason=utf8_page");
                dispose(active);active=NULL;return;
            }
            if (bsp_display_lock(1)) {
                bool valid=generation_matches(active->generation);
                if (label) lv_label_set_text(label,valid?page:"");
                /* Cancellation is asynchronous; clear before releasing the UI
                 * lock if the generation changed during the label update. */
                if (label && !generation_matches(active->generation)) lv_label_set_text(label,"");
                bsp_display_unlock(); offset=cursor; next_page=now+pdMS_TO_TICKS(3500);
                if (!active->text[offset]) { dispose(active);active=NULL; }
            }
        }

}

void caption_ui_task(void *unused)
{
    (void)unused;
    portENTER_CRITICAL(&mux); worker_ready=true; portEXIT_CRITICAL(&mux);
    while(true) { caption_ui_step(); vTaskDelay(pdMS_TO_TICKS(50)); }
}
#ifdef CAPTION_UI_HOST_TEST
void caption_ui_test_step(void) { worker_ready=true;caption_ui_step(); }
#endif
