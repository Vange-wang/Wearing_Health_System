/* Included after the legacy codec adapters. The capture producer owns no HTTP
 * object. All storage operations are short and serialized; no I/O under lock. */
static SemaphoreHandle_t s_v2_lock;
static v2_capture_t s_v2_capture;
/* Protected by s_v2_lock. Recovery cannot revive input from a failed turn. */
static uint32_t s_v2_retired_generation;
static char s_v2_session[33];
static bool s_v2_registered;
static service_origin_snapshot_t s_v2_origin;
static TaskHandle_t s_v2_session_task_handle;
static uint32_t s_v2_turn;
static bool s_v2_turn_used;
static uint32_t s_v2_bound_generation;
typedef struct { uint32_t generation, revision; bool response,transport_failed; service_origin_snapshot_t origin;
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    uint32_t cancel_reason,wake_checked,wake_cancelled;
#endif
 } v2_cancel_context_t;
static voice_v2_transport_t s_v2_prepared;
static v2_cancel_context_t s_v2_prepared_cancel;
static int64_t s_v2_prepared_us;
static v2_cancel_context_t s_v2_output_context;
static voice_v2_identity_t s_v2_output_id;
static volatile bool s_v2_output_active, s_v2_player_busy, s_v2_player_failed;
typedef struct { uint32_t generation,revision,frame; uint64_t origin_epoch; size_t size; uint8_t data[4096]; } v2_play_item_t;
static QueueHandle_t s_v2_play_queue;
static StaticQueue_t s_v2_play_queue_state;
static uint8_t *s_v2_play_queue_storage;
static volatile uint32_t s_v2_play_frame;
#define V2_PENDING_CAPTIONS 192U
typedef struct {
    v2_play_item_t rx,play;
    char *caption[V2_PENDING_CAPTIONS];
    uint32_t frame[V2_PENDING_CAPTIONS],generation[V2_PENDING_CAPTIONS],revision[V2_PENDING_CAPTIONS];
    char prior_started[96],prior_terminal[512],prior_header[1025];
} v2_psram_work_t;
static v2_psram_work_t *s_v2_work;
#define s_v2_rx_item (s_v2_work->rx)
#define s_v2_play_item (s_v2_work->play)
#define s_v2_pending_caption (s_v2_work->caption)
#define s_v2_pending_frame (s_v2_work->frame)
#define s_v2_pending_generation (s_v2_work->generation)
#define s_v2_pending_revision (s_v2_work->revision)
#define s_v2_prior_started (s_v2_work->prior_started)
#define s_v2_prior_terminal (s_v2_work->prior_terminal)
#define s_v2_prior_header (s_v2_work->prior_header)
static uint32_t s_v2_last_audio_frame;
static bool s_v2_queued_pcm;
typedef struct {voice_v2_identity_t id;char body[512];} v2_event_item_t;
static QueueHandle_t s_v2_event_queue;
static StaticQueue_t s_v2_event_queue_state;
static uint8_t *s_v2_event_queue_storage;
static voice_v2_identity_t s_v2_prior_id;
static const char *v2_prior_header(const voice_v2_identity_t *id)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    s_v2_prior_header[0]=0;
    if(id->turn>1 && id->turn-1==s_v2_prior_id.turn && !strcmp(id->session,s_v2_prior_id.session) && s_v2_prior_started[0]) {
        int n=snprintf(s_v2_prior_header,sizeof(s_v2_prior_header),"{\"session\":\"%s\",\"turn\":%lu,\"revision\":%lu,\"events\":[%s%s%s]}",
            s_v2_prior_id.session,(unsigned long)s_v2_prior_id.turn,(unsigned long)s_v2_prior_id.revision,
            s_v2_prior_started,s_v2_prior_terminal[0]?",":"",s_v2_prior_terminal);
        if(n<=0 || (size_t)n>=sizeof(s_v2_prior_header))s_v2_prior_header[0]=0;
    }
    xSemaphoreGive(s_v2_lock);return s_v2_prior_header;
}
static volatile bool s_v2_tail;
static volatile unsigned s_v2_tail_quiet_frames;
static void v2_event_task(void *arg)
{
    (void)arg;v2_event_item_t item;
    while(true)if(xQueueReceive(s_v2_event_queue,&item,portMAX_DELAY)==pdTRUE) {
        if(!voice_v2_event(&item.id,item.body,strlen(item.body)))
            ESP_LOGW(TAG,"v2:event_delivery_failed turn=%lu revision=%lu",(unsigned long)item.id.turn,(unsigned long)item.id.revision);
    }
}
static bool v2_post_event(const char *body)
{
    v2_event_item_t item={.id=s_v2_output_id};
    size_t n=strlen(body);if(n>=sizeof(item.body))return false;
    memcpy(item.body,body,n+1);
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    if(item.id.turn==s_v2_prior_id.turn && !strcmp(item.id.session,s_v2_prior_id.session) &&
       strstr(s_v2_prior_terminal,"play_finished") && strstr(body,"interrupted")) {
        xSemaphoreGive(s_v2_lock);return true;
    }
    if(s_v2_prior_id.turn!=item.id.turn || strcmp(s_v2_prior_id.session,item.id.session) || s_v2_prior_id.revision!=item.id.revision) {
        s_v2_prior_id=item.id;s_v2_prior_started[0]=s_v2_prior_terminal[0]=0;
    }
    bool started=strstr(body,"play_started")!=NULL;
    if(started && n<sizeof(s_v2_prior_started))memcpy(s_v2_prior_started,body,n+1);
    else if(!started)memcpy(s_v2_prior_terminal,body,n+1);
    xSemaphoreGive(s_v2_lock);
    return xQueueSend(s_v2_event_queue,&item,0)==pdTRUE;
}
static void v2_tail_observe(const int16_t *pairs,const int16_t *clean,size_t samples)
{
    if(!s_v2_tail || samples!=DUPLEX_AUDIO_AEC_FRAME_SAMPLES)return;
    uint64_t reference=0,residual=0;
    for(size_t i=0;i<samples;i++) {
        int32_t r=pairs[i*2+1],m=clean[i];reference+=(uint64_t)(r*r);residual+=(uint64_t)(m*m);
    }
    reference/=samples;residual/=samples;
    duplex_audio_stats_t stats=duplex_audio_stats();
    uint64_t gate=stats.noise_floor*4U;if(gate<1024U)gate=1024U;
    if(!stats.degraded && reference<=1024U && residual<=gate)s_v2_tail_quiet_frames++;
    else s_v2_tail_quiet_frames=0;
}
static void v2_player_task(void *arg);
static bool v2_admit_pcm(void *unused)
{
    (void)unused;
    return v2_capture_pcm_begin(&s_v2_capture,s_v2_output_context.revision);
}
static bool v2_begin_first_pcm(uint32_t generation)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool ok=!s_origin_cancel_requested && service_origin_current(&s_v2_output_context.origin) && s_v2_output_active && s_v2_output_context.generation==generation &&
        s_v2_capture.generation==generation &&
        wake_engine_admit_output(generation,v2_admit_pcm,NULL);
    xSemaphoreGive(s_v2_lock);
    return ok;
}
static bool v2_complete_first_pcm(uint32_t generation,bool success)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool current=!s_origin_cancel_requested && service_origin_current(&s_v2_output_context.origin) && s_v2_capture.generation==generation && s_v2_output_context.generation==generation;
    bool ok=current && v2_capture_pcm_complete(&s_v2_capture,s_v2_output_context.revision,success);
    bool pending=current && s_v2_capture.continuation_pending;
    /* Capture can publish UPLOADING before reaching v2_resume_if_ready.
     * Atomically arbitrate that wake-state transition as well. */
    int wake_result=current?wake_engine_commit_output(generation,ok):0;
    pending=pending || wake_result==2;
    xSemaphoreGive(s_v2_lock);
    if(ok) {
#ifdef VOICE_PUBLIC_PCM_INJECTION
        public_pcm_response_event(1U);
#endif
        s_response_playback_started_us=esp_timer_get_time();
        char event[96];snprintf(event,sizeof(event),"{\"seq\":1,\"kind\":\"play_started\",\"generation\":%lu}",(unsigned long)generation);
        if(!v2_post_event(event))ESP_LOGW(TAG,"v2:event_queue_full kind=play_started");
    }
    if(pending) {
        /* Includes failed/partial codec writes: preserve confirmed new speech,
         * while leaving the failed old output uncommitted to history. */
        (void)wake_engine_restart_deferred_input(generation);
        (void)audio_session_cancel_talk(generation);
        bsp_audio_tx_cancel(generation);
        notify_talk_task();
        return false;
    }
    if(ok)ok=wake_result==1;
    if(ok)caption_ui_begin(generation);
    return ok;
}

#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
static bool v2_cancelled(void *arg)
{
    v2_cancel_context_t *c=arg;
    if(s_origin_cancel_requested){c->cancel_reason=1;return true;}
    if(!service_origin_current(&c->origin)){c->cancel_reason=2;return true;}
    c->wake_checked=1;c->wake_cancelled=wake_engine_should_cancel(c->generation)?1U:0U;
    if(c->wake_cancelled){c->cancel_reason=3;return true;}
    if(s_capture_fault){c->cancel_reason=4;return true;}
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool stop=s_v2_capture.generation!=c->generation || s_v2_capture.failed ||
        (c->response && s_v2_capture.revision!=c->revision);
    if(stop)c->cancel_reason=s_v2_capture.generation!=c->generation?5U:s_v2_capture.failed?6U:7U;
    xSemaphoreGive(s_v2_lock);return stop;
}
#else
static bool v2_cancelled(void *arg)
{
    v2_cancel_context_t *c=arg;
    if(s_origin_cancel_requested || !service_origin_current(&c->origin) || wake_engine_should_cancel(c->generation) || s_capture_fault)return true;
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool stop=s_v2_capture.generation!=c->generation || s_v2_capture.failed ||
        (c->response && s_v2_capture.revision!=c->revision);
    xSemaphoreGive(s_v2_lock);return stop;
}
#endif
static bool v2_read(voice_v2_transport_t *transport,void *data,size_t size)
{
    bool ok=voice_v2_read_exact(transport,data,size);
    v2_cancel_context_t *ctx=transport->user;
    if(!ok && !v2_cancelled(ctx))ctx->transport_failed=true;
    return ok;
}
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
static void v2_failure_note(const voice_v2_identity_t *id,const voice_v2_transport_t *t,
    const v2_cancel_context_t *c,uint32_t op,int slot,bool prepared,uint32_t invalidated,
    uint32_t cap_failed,uint32_t cap_gen,uint32_t cap_rev,uint32_t slot_state)
{
    const voice_v2_failure_t *f=&t->failure;
    ESP_LOGW(TAG,"v2diag:failure op=%lu valid=%lu stage=%lu rc=%ld errno=%ld errno_valid=%lu generation=%lu revision=%lu turn=%lu samples=%lu progress_us=%lld prepared=%u prepared_age_us=%lld invalidated=%lu cancel_reason=%lu wake_checked=%lu wake_cancelled=%lu origin_cancel=%u capture_fault=%u capture_failed=%lu cap_gen=%lu cap_rev=%lu slot=%d slot_state=%lu",
        (unsigned long)op,(unsigned long)f->valid,(unsigned long)f->stage,(long)f->rc,(long)f->error_number,(unsigned long)f->errno_valid,
        (unsigned long)c->generation,(unsigned long)id->revision,(unsigned long)id->turn,(unsigned long)f->samples,(long long)f->last_progress_us,
        prepared?1U:0U,prepared?(long long)(esp_timer_get_time()-s_v2_prepared_us):0LL,(unsigned long)invalidated,
        (unsigned long)c->cancel_reason,(unsigned long)c->wake_checked,(unsigned long)c->wake_cancelled,
        s_origin_cancel_requested?1U:0U,s_capture_fault?1U:0U,(unsigned long)cap_failed,(unsigned long)cap_gen,(unsigned long)cap_rev,slot,(unsigned long)slot_state);
}
#define VF_OP(n) (failure_op=(n))
#define VF_INVALIDATE(id,t,c,op,slot,prepared) v2_invalidate_session((id),(c)->generation,(t),(c),(op),(slot),(prepared))
#define VF_OPEN_NOTE(id,t,c,op) v2_failure_note((id),(t),(c),(op),-1,false,0,0,0,0,0)
#else
#define VF_OP(n) ((void)0)
#define VF_INVALIDATE(id,t,c,op,slot,prepared) v2_invalidate_session((id),(c)->generation)
#define VF_OPEN_NOTE(id,t,c,op) ((void)0)
#endif
static void v2_invalidate_session(const voice_v2_identity_t *id, uint32_t generation
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    ,const voice_v2_transport_t *t,const v2_cancel_context_t *c,uint32_t op,int slot,bool prepared
#endif
)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool current=id && generation != 0 && generation==s_v2_bound_generation &&
        generation==s_v2_capture.generation && id->turn==s_v2_turn &&
        id->origin.epoch==s_v2_origin.epoch &&
        id->origin.wifi_generation==s_v2_origin.wifi_generation && !strcmp(id->session,s_v2_session);
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    uint32_t cap_failed=s_v2_capture.failed,cap_gen=s_v2_capture.generation,cap_rev=s_v2_capture.revision;
    uint32_t slot_state=slot>=0 && slot<2?s_v2_capture.slots[slot].state:UINT32_MAX;
#endif
    if(current){
        s_v2_retired_generation=generation;
        s_v2_registered=false;
        service_origin_session(&id->origin,false);
    }
    xSemaphoreGive(s_v2_lock);
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
    v2_failure_note(id,t,c,op,slot,prepared,current?1U:0U,cap_failed,cap_gen,cap_rev,slot_state);
#endif
    if(current) {
        /* Input retirement is not a capture-capacity failure and owns no ACK lease. */
        (void)audio_session_stop_capture(generation);
        origin_notify_background();
    }
}
static void v2_session_task(void *arg)
{
    (void)arg;
    while(true) {
        bool idle=!audio_session_capture_pending() && !audio_session_capture_active() &&
            !audio_session_owner_is(AUDIO_SESSION_OWNER_TALK) && !audio_session_owner_is(AUDIO_SESSION_OWNER_ALERT) &&
            !s_v2_output_active && !s_v2_player_busy && !s_v2_tail && !s_v2_prepared.client && uxQueueMessagesWaiting(s_v2_play_queue)==0;
        service_origin_action_t action=service_origin_candidate(idle,esp_timer_get_time());
        if(action==ORIGIN_CANCEL_OLD){
            s_origin_cancel_requested=true;
            uint32_t generation=audio_session_capture_generation();
            xSemaphoreTake(s_v2_lock,portMAX_DELAY);s_v2_capture.failed=true;xSemaphoreGive(s_v2_lock);
            (void)audio_session_stop_capture(generation);(void)audio_session_cancel_talk(generation);
            audio_session_cancel_alert();(void)wake_engine_finish_round(generation,false);bsp_audio_tx_cancel(generation);notify_talk_task();
        }else if(action==ORIGIN_CAN_PUBLISH){
            /* All HTTP/codec owners are idle. Revoke old session/context first;
             * only then atomically publish after nonce/network revalidation. */
            xSemaphoreTake(s_v2_lock,portMAX_DELAY);
            s_v2_registered=false;service_origin_session(&s_v2_origin,false);
            memset(s_v2_session,0,sizeof(s_v2_session));
            memset(&s_v2_output_id,0,sizeof(s_v2_output_id));memset(&s_v2_prior_id,0,sizeof(s_v2_prior_id));
            s_v2_prior_started[0]=s_v2_prior_terminal[0]=s_v2_prior_header[0]=0;
            xSemaphoreGive(s_v2_lock);
            service_origin_snapshot_t fresh;
            if(service_origin_publish(true,esp_timer_get_time(),&fresh)){
                s_origin_cancel_requested=false;origin_notify_background();
                ESP_LOGI(TAG,"origin:published epoch=%" PRIu64,fresh.epoch);
            }
        }
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        if(s_v2_registered && !service_origin_session_valid(&s_v2_origin))s_v2_registered=false;
        bool needs_registration=!s_v2_registered;
        xSemaphoreGive(s_v2_lock);
        service_origin_snapshot_t origin;
        if(s_wifi_up && needs_registration && service_origin_acquire(&origin,false)) {
            char session[33];
            if(voice_v2_register_session(&origin,session)) {
                xSemaphoreTake(s_v2_lock,portMAX_DELAY);
                bool committed=service_origin_current(&origin);
                if(committed){
                    memcpy(s_v2_session,session,sizeof(session));s_v2_origin=origin;
                    s_v2_turn=1;s_v2_turn_used=false;
                    service_origin_session(&origin,true);
                    s_v2_registered=service_origin_session_valid(&origin);
                    committed=s_v2_registered;
                }
                xSemaphoreGive(s_v2_lock);
                if(committed)ESP_LOGI(TAG,"v2:session_ready");
            }
        }
        service_origin_snapshot_t hint_ready;
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        bool hint_complete=s_v2_registered && service_origin_acquire(&hint_ready,true) &&
            hint_ready.epoch==s_v2_origin.epoch && hint_ready.wifi_generation==s_v2_origin.wifi_generation;
        xSemaphoreGive(s_v2_lock);
        if(hint_complete)discovery_hint_note_ready(&hint_ready);
        (void)ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(action==ORIGIN_WAIT_IDLE || action==ORIGIN_CANCEL_OLD?100:(s_v2_registered?1000:2000)));
    }
}
static bool v2_runtime_init(void)
{
    s_v2_work=heap_caps_calloc(1,sizeof(*s_v2_work),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!s_v2_work)return false;
    s_v2_lock=xSemaphoreCreateMutex();
    int16_t *a=heap_caps_calloc(V2_CAPTURE_SEGMENT_SAMPLES,sizeof(int16_t),MALLOC_CAP_SPIRAM);
    int16_t *b=heap_caps_calloc(V2_CAPTURE_SEGMENT_SAMPLES,sizeof(int16_t),MALLOC_CAP_SPIRAM);
    if(!s_v2_lock || !a || !b){free(a);free(b);return false;}
    v2_capture_init(&s_v2_capture,a,b);
    /* Payloads are task-only; do not consume a >9 KB contiguous internal block
     * after the wake model/NimBLE have fragmented internal RAM. */
    s_v2_event_queue_storage=heap_caps_calloc(16,sizeof(v2_event_item_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!s_v2_event_queue_storage)return false;
    s_v2_event_queue=xQueueCreateStatic(16,sizeof(v2_event_item_t),s_v2_event_queue_storage,&s_v2_event_queue_state);
    if(!s_v2_event_queue || xTaskCreateWithCaps(v2_event_task,"v2_events",4096,NULL,3,NULL,
        MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)!=pdPASS)return false;
    s_v2_play_queue_storage=heap_caps_calloc(160,sizeof(v2_play_item_t),MALLOC_CAP_SPIRAM);
    if(!s_v2_play_queue_storage)return false;
    s_v2_play_queue=xQueueCreateStatic(160,sizeof(v2_play_item_t),s_v2_play_queue_storage,&s_v2_play_queue_state);
    if(!s_v2_play_queue || xTaskCreateWithCaps(v2_player_task,"v2_player",8192,NULL,5,NULL,
        MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)!=pdPASS)return false;
    ESP_LOGI(TAG,"v2:buffer_budget capture_psram=%u play_queue_psram=%u event_queue_psram=%u work_psram=%u internal_free=%u internal_largest=%u",
        (unsigned)(2U*V2_CAPTURE_SEGMENT_SAMPLES*sizeof(int16_t)),
        (unsigned)(160U*sizeof(v2_play_item_t)),(unsigned)(16U*sizeof(v2_event_item_t)),
        (unsigned)sizeof(*s_v2_work),
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
    wake_engine_enable_segmented_input();
    return xTaskCreateWithCaps(v2_session_task,"v2_session",4096,NULL,3,&s_v2_session_task_handle,
        MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)==pdPASS;
}
static bool v2_bind(uint32_t generation)
{
    if(!generation || !s_v2_lock || !s_v2_registered || !service_origin_current(&s_v2_origin))return false;
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool ok=s_v2_turn<UINT32_MAX && s_v2_retired_generation!=generation;
    if(ok && s_v2_bound_generation!=generation) {
        v2_capture_reset(&s_v2_capture,generation);
        s_v2_bound_generation=generation;
        if(!s_v2_turn || s_v2_turn_used)s_v2_turn++;
        s_v2_turn_used=false;
    }
    ok=ok && !s_v2_capture.failed;
    xSemaphoreGive(s_v2_lock);return ok;
}
static bool v2_capture_input_retired(uint32_t generation)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool current = generation != 0 && s_v2_bound_generation==generation &&
                   s_v2_capture.generation==generation;
    bool unavailable = !s_v2_registered || !service_origin_current(&s_v2_origin);
    if (current && unavailable) s_v2_retired_generation=generation;
    bool retired = !current || s_v2_retired_generation==generation || unavailable;
    xSemaphoreGive(s_v2_lock);
    return retired;
}

static bool v2_capture_write(const int16_t *pcm,size_t count,uint32_t generation,
                             bool *input_retired)
{
    if(!v2_bind(generation)) {
        if(input_retired)*input_retired=v2_capture_input_retired(generation);
        return false;
    }
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool current=s_v2_bound_generation==generation && s_v2_capture.generation==generation;
    bool unavailable=!s_v2_registered || !service_origin_current(&s_v2_origin);
    if(current && unavailable)s_v2_retired_generation=generation;
    bool retired=!current || s_v2_retired_generation==generation || unavailable;
    bool ok=!retired && v2_capture_append(&s_v2_capture,pcm,count);
    /* Classify the actual append attempt under the same lock. A later network
     * invalidation must not relabel an already observed capacity failure. */
    if(input_retired)*input_retired=retired;
    xSemaphoreGive(s_v2_lock);notify_talk_task();return ok;
}
static void v2_preconnect(uint32_t generation)
{
    voice_v2_close(&s_v2_prepared);
    if(!v2_bind(generation))return;
    if(!s_v2_registered)return;
    voice_v2_identity_t id={0};
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    memcpy(id.session,s_v2_session,sizeof(id.session));id.turn=s_v2_turn;id.revision=1;id.origin=s_v2_origin;
    xSemaphoreGive(s_v2_lock);
    s_v2_prepared_cancel=(v2_cancel_context_t){.generation=generation,.revision=1,.origin=id.origin};
    if(voice_v2_open(&s_v2_prepared,&id,v2_cancelled,&s_v2_prepared_cancel,v2_prior_header(&id)))
        s_v2_prepared_us=esp_timer_get_time();
    else VF_OPEN_NOTE(&id,&s_v2_prepared,&s_v2_prepared_cancel,7);
}
static void v2_endpoint(uint32_t generation,bool cancel)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool current=s_v2_capture.generation==generation;
    if(current && cancel)s_v2_capture.failed=true;
    else if(current && !s_v2_capture.waiting && !s_v2_capture.playing)
        (void)v2_capture_endpoint(&s_v2_capture);
    xSemaphoreGive(s_v2_lock);
    if(current && !cancel)(void)wake_engine_wait_candidate(generation);
    notify_talk_task();
}
static bool v2_resume_if_ready(uint32_t generation)
{
    if(wake_engine_state()!=WAKE_ENGINE_STATE_UPLOADING || audio_session_capture_active())return false;
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool ok=s_v2_capture.generation==generation && s_v2_capture.waiting &&
        !s_v2_capture.playing && v2_capture_continue(&s_v2_capture);
    if(s_v2_capture.generation==generation && s_v2_capture.continuation_pending)
        (void)wake_engine_defer_input(generation);
    xSemaphoreGive(s_v2_lock);
    return ok && audio_session_resume_capture(generation);
}
static uint32_t v2_be32(const uint8_t *p)
{return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}

static int v2_queue_output(void *arg,const uint8_t *pcm,size_t length)
{
    v2_cancel_context_t *cancel=arg;
    if(!length || length>sizeof(s_v2_rx_item.data))return -1;
    s_v2_rx_item.generation=cancel->generation;s_v2_rx_item.revision=cancel->revision;
    s_v2_rx_item.origin_epoch=cancel->origin.epoch;
    s_v2_rx_item.frame=s_v2_last_audio_frame;
    size_t sent=0;
    while(sent<length) {
        size_t take=length-sent;
        /* First hardware submission is only 4 ms of stereo, so state/caption
         * ownership is established before consuming the rest of this chunk. */
        if(!s_v2_queued_pcm && take>256)take=256;
        s_v2_rx_item.size=take;memcpy(s_v2_rx_item.data,pcm+sent,take);
        bool queued=false;
        while(!v2_cancelled(cancel) && !s_v2_player_failed)
            if(xQueueSend(s_v2_play_queue,&s_v2_rx_item,pdMS_TO_TICKS(10))==pdTRUE){queued=true;break;}
        if(!queued)return -1;
        s_v2_queued_pcm=true;sent+=take;
    }
    return (int)length;
}
static bool v2_caption_received(char *text,uint32_t frame)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool immediate=s_v2_play_frame>=frame && s_response_playback_started_us>0;
    if(!immediate) {
        unsigned slot=0;
        while(slot<V2_PENDING_CAPTIONS && s_v2_pending_caption[slot])slot++;
        if(slot==V2_PENDING_CAPTIONS){xSemaphoreGive(s_v2_lock);free(text);return false;}
        s_v2_pending_caption[slot]=text;s_v2_pending_frame[slot]=frame;
        s_v2_pending_generation[slot]=s_v2_output_context.generation;
        s_v2_pending_revision[slot]=s_v2_output_context.revision;
    }
    xSemaphoreGive(s_v2_lock);
    if(immediate)caption_ui_submit(text,s_v2_output_context.generation);
    return true;
}
static void v2_player_task(void *arg)
{
    (void)arg;
    while(true) {
        /* Busy is set while holding the same mutex used by the empty-queue
         * completion check, so dequeue cannot create a false drained window. */
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        bool got=xQueueReceive(s_v2_play_queue,&s_v2_play_item,0)==pdTRUE;
        if(got)s_v2_player_busy=true;
        xSemaphoreGive(s_v2_lock);
        if(!got){vTaskDelay(1);continue;}
        v2_cancel_context_t local={.generation=s_v2_play_item.generation,
            .revision=s_v2_play_item.revision,.response=true,.origin=s_v2_output_context.origin};
        bool ok=s_v2_play_item.origin_epoch==local.origin.epoch && s_v2_output_active && !v2_cancelled(&local);
        if(ok) {
            codec_output_context_t ctx={.owner=AUDIO_SESSION_OWNER_TALK,.generation=local.generation,
                .duplex_reference=true,.response_output=true};
            ok=codec_output_write(&ctx,s_v2_play_item.data,s_v2_play_item.size)==(int)s_v2_play_item.size;
        }
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        if(ok && s_v2_capture.generation==local.generation && s_v2_capture.revision==local.revision) {
            ok=v2_capture_mark_playing(&s_v2_capture,local.revision);
            s_v2_play_frame=s_v2_play_item.frame;
        }
        if(!ok)s_v2_player_failed=true;
        xSemaphoreGive(s_v2_lock);
        if(ok)for(unsigned slot=0;slot<V2_PENDING_CAPTIONS;slot++) {
            xSemaphoreTake(s_v2_lock,portMAX_DELAY);
            char *caption=NULL;
            if(s_v2_pending_frame[slot]<=s_v2_play_item.frame && s_v2_pending_caption[slot] &&
               s_v2_pending_generation[slot]==local.generation && s_v2_pending_revision[slot]==local.revision) {
                caption=s_v2_pending_caption[slot];s_v2_pending_caption[slot]=NULL;
            }
            xSemaphoreGive(s_v2_lock);
            if(caption)caption_ui_submit(caption,local.generation);
        }
        memset(s_v2_play_item.data,0,s_v2_play_item.size);
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        s_v2_player_busy=false;
        xSemaphoreGive(s_v2_lock);
    }
}

/* RX never calls the codec. The player starts with the first queued chunk;
 * capacity is a bound, not a startup watermark. */
static bool v2_receive(voice_v2_transport_t *t,v2_cancel_context_t *cancel)
{
    uint32_t frames=0;bool output=false,complete=false;
    cancel->response=true;
    s_v2_output_context=*cancel;s_v2_output_id=t->id;
    s_v2_player_failed=false;s_v2_play_frame=0;s_v2_queued_pcm=false;s_v2_output_active=true;
    while(!v2_cancelled(cancel)) {
        uint8_t h[5];if(!v2_read(t,h,sizeof(h)))break;
        uint32_t n=v2_be32(h+1);
        if(h[0]=='M' || h[0]=='D' || h[0]=='X') {
            char meta[513];if(!n || n>512 || !v2_read(t,meta,n))break;
            meta[n]=0;
            cJSON *j=cJSON_ParseWithLength(meta,n);
            if(!j)break;
            if(h[0]=='D') {
                cJSON *f=cJSON_GetObjectItemCaseSensitive(j,"frames");
                complete=cJSON_IsNumber(f) && f->valuedouble==frames;
#ifdef VOICE_PUBLIC_PCM_INJECTION
                if(complete)public_pcm_response_event(2U);
#endif
                cJSON_Delete(j);break;
            }
            bool terminal=h[0]=='X';cJSON_Delete(j);if(terminal)break;
            continue;
        }
        if(h[0]!='F' || n<8 || n>MAX_FRAME+8U)break;
        uint8_t fh[8];if(!v2_read(t,fh,sizeof(fh)))break;
        uint32_t seq=v2_be32(fh),len=v2_be32(fh+4);
        if(seq!=frames+1)break;
        if(len==UINT32_MAX) {
            uint8_t count[8];if(n<16 || !v2_read(t,count,8))break;
            uint64_t size=0;for(unsigned i=0;i<8;i++)size=(size<<8)|count[i];
            if(size>512 || size!=n-16)break;
            char *text=heap_caps_malloc((size_t)size+1,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
            if(!text || !v2_read(t,text,(size_t)size)){free(text);break;}
            text[size]=0;
            if(caption_text_valid(text,(size_t)size) && !v2_cancelled(cancel)) {
                if(!v2_caption_received(text,s_v2_last_audio_frame)) {
                    ESP_LOGE(TAG,"v2:caption_capacity");break;
                }
            } else free(text);
            frames++;continue;
        }
        if(len!=n-8 || len<WAV_STREAM_HEADER_BYTES)break;
        uint8_t wav[WAV_STREAM_HEADER_BYTES];
        if(!v2_read(t,wav,sizeof(wav)))break;
        if(!output) {
            if(!duplex_audio_begin_playback(DUPLEX_PLAYBACK_RESPONSE_INTERRUPTIBLE,cancel->generation))break;
            bsp_audio_tx_begin(cancel->generation);output=true;
        }
        s_v2_last_audio_frame=seq;
        wav_stream_t stream;
        wav_stream_result_t r=wav_stream_begin(&stream,wav,sizeof(wav),len,esp_get_free_heap_size(),
            s_playback_stereo,sizeof(s_playback_stereo)/sizeof(s_playback_stereo[0]),v2_queue_output,v2_cancelled,cancel);
        size_t left=len-sizeof(wav);
        while(r==WAV_STREAM_OK && left && !v2_cancelled(cancel)) {
            size_t take=left<sizeof(s_wav_pcm)?left:sizeof(s_wav_pcm);
            if(!v2_read(t,s_wav_pcm,take)){r=WAV_STREAM_TRUNCATED;break;}
            r=wav_stream_write(&stream,s_wav_pcm,take);left-=take;
        }
        if(r!=WAV_STREAM_OK || left || wav_stream_end(&stream)!=WAV_STREAM_OK)break;
        frames++;
    }
    while(complete && !v2_cancelled(cancel) && !s_v2_player_failed) {
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        bool drained=!s_v2_player_busy && uxQueueMessagesWaiting(s_v2_play_queue)==0;
        xSemaphoreGive(s_v2_lock);
        if(drained)break;
        vTaskDelay(1);
    }
    complete=complete && !v2_cancelled(cancel) && !s_v2_player_failed;
    s_v2_output_active=false;
    while(s_v2_player_busy)vTaskDelay(1);
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    xQueueReset(s_v2_play_queue);
    for(unsigned i=0;i<V2_PENDING_CAPTIONS;i++){free(s_v2_pending_caption[i]);s_v2_pending_caption[i]=NULL;s_v2_pending_frame[i]=0;}
    xSemaphoreGive(s_v2_lock);
    if(complete && output) {
        tx_dma_fence_t fence;uint64_t completed_seq=0;
        bool fenced=bsp_audio_tx_fence(cancel->generation,&fence);
        int64_t deadline=esp_timer_get_time()+1000000;
        while(fenced && !v2_cancelled(cancel) && esp_timer_get_time()<deadline &&
              !bsp_audio_tx_receipt(&fence,&completed_seq))vTaskDelay(1);
        if(fenced && completed_seq && !v2_cancelled(cancel)) {
            char event[512];
            int n=snprintf(event,sizeof(event),"{\"seq\":2,\"kind\":\"play_finished\",\"frames\":%lu,\"completion\":\"tx_dma_completed\",\"tx\":{\"epoch\":%lu,\"accepted_bytes\":%llu,\"completed_bytes\":%llu,\"write_count\":%llu,\"fence_seq\":%llu,\"complete_seq\":%llu,\"descriptor_count\":6,\"descriptor_mask\":63,\"unknown_partial\":false,\"events_lost\":0,\"cancelled\":false,\"session\":\"%s\",\"turn\":%lu,\"revision\":%lu,\"generation\":%lu}}",
                (unsigned long)frames,(unsigned long)fence.output_epoch,
                (unsigned long long)fence.accepted,(unsigned long long)fence.accepted,
                (unsigned long long)fence.writes,(unsigned long long)fence.sequence,
                (unsigned long long)completed_seq,t->id.session,(unsigned long)t->id.turn,
                (unsigned long)t->id.revision,(unsigned long)cancel->generation);
            if(n<=0 || (size_t)n>=sizeof(event) || !v2_post_event(event))complete=false;
#ifdef VOICE_PUBLIC_PCM_INJECTION
            if(complete)public_pcm_response_event(3U);
#endif
        }else complete=false;
        /* DMA completion does not clear acoustic state. Quiet is measured
         * while the existing near-speech detector remains interruptible. */
        s_v2_tail_quiet_frames=0;s_v2_tail=true;deadline=esp_timer_get_time()+3000000;
        while(!v2_cancelled(cancel) && s_v2_tail_quiet_frames<4 && esp_timer_get_time()<deadline)vTaskDelay(1);
        bool tail_timeout=!v2_cancelled(cancel) && s_v2_tail_quiet_frames<4;
        s_v2_tail=false;
        if(tail_timeout) {
            ESP_LOGE(TAG,"v2:tail_unresolved capture_recovery=1");
            duplex_audio_capture_gap();s_capture_fault=true;s_voice_tasks_ready=false;complete=false;
        }
    }
    if(!complete && s_response_playback_started_us>0)
        (void)v2_post_event("{\"seq\":3,\"kind\":\"interrupted\"}");
    if(output)duplex_audio_end_playback();
    if(!complete)bsp_audio_tx_cancel(cancel->generation);
    caption_ui_cancel(cancel->generation);s_response_playback_started_us=0;
#ifdef VOICE_PUBLIC_PCM_INJECTION
    public_pcm_response_event(complete?4U:5U);
#endif
    return complete;
}
static bool v2_input_continued(uint32_t generation,uint32_t revision)
{
    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
    bool current=s_v2_capture.generation==generation && !s_v2_capture.failed && !s_v2_capture.playing;
    /* The capture task may be preempted between wake confirmation and resume.
     * Preserve the same turn until that already-confirmed input is admitted. */
    bool continued=current && (s_v2_capture.revision>revision ||
        (s_v2_capture.waiting && !s_v2_capture.committing &&
         wake_engine_state()==WAKE_ENGINE_STATE_UPLOADING && wake_engine_generation()==generation));
    xSemaphoreGive(s_v2_lock);return continued;
}
/* Called only at the response boundary, never before input upload. */
static bool v2_receive_with_lease(voice_v2_transport_t *transport,
                                  v2_cancel_context_t *cancel)
{
    bool leased = false;
    while (!v2_cancelled(cancel)) {
        if (!ack_cleanup_pending(cancel->generation) &&
            audio_session_acquire_playback(AUDIO_SESSION_OWNER_TALK)) {
            leased = true;
            break;
        }
        ulTaskNotifyTake(pdTRUE, 1);
    }
    if (!leased) return false;
    bool done = !v2_cancelled(cancel) && v2_receive(transport, cancel);
    audio_session_release(AUDIO_SESSION_OWNER_TALK);
    return done;
}

static void v2_voice_round(uint32_t generation)
{
    if(!v2_bind(generation))return;
    v2_cancel_context_t cancel={.generation=generation,.origin=s_v2_origin};
    /* A known lost session is recovered in the background. Retain the user's
     * new input in the bounded store instead of spending it on a stale session. */
    if(!s_v2_registered || !service_origin_current(&cancel.origin))return;
    while(!v2_cancelled(&cancel)) {
        xSemaphoreTake(s_v2_lock,portMAX_DELAY);
        int slot=v2_capture_acquire(&s_v2_capture);
        voice_v2_identity_t id={.turn=s_v2_turn,.origin=s_v2_origin};memcpy(id.session,s_v2_session,sizeof(id.session));
        if(slot>=0){id.segment=s_v2_capture.slots[slot].seq;id.sample_start=s_v2_capture.slots[slot].start;id.revision=id.segment+1;}
        xSemaphoreGive(s_v2_lock);
        if(slot<0){ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(10));continue;}
        cancel.revision=id.revision;cancel.response=false;
        voice_v2_transport_t transport={0};
#ifdef VOICE_V2_FAILURE_DIAGNOSTICS
        uint32_t failure_op=0;
#endif
        bool prepared=s_v2_prepared.client && s_v2_prepared_cancel.generation==generation &&
            id.segment==0 && esp_timer_get_time()-s_v2_prepared_us<4000000;
        if(prepared) {
            transport=s_v2_prepared;memset(&s_v2_prepared,0,sizeof(s_v2_prepared));
            transport.cancelled=v2_cancelled;transport.user=&cancel;
        } else {
            voice_v2_close(&s_v2_prepared);
            if(!voice_v2_open(&transport,&id,v2_cancelled,&cancel,v2_prior_header(&id))){VF_OPEN_NOTE(&id,&transport,&cancel,1);break;}
        }
        bool sent=false,limit=false,ok=true;
        while(!v2_cancelled(&cancel)) {
            xSemaphoreTake(s_v2_lock,portMAX_DELAY);
            bool current=s_v2_capture.generation==generation;
            size_t count=current?v2_capture_read(&s_v2_capture,slot,s_upload_mono,sizeof(s_upload_mono)/sizeof(s_upload_mono[0])):0;
            v2_capture_slot_t *part=&s_v2_capture.slots[slot];
            bool sealed=current && part->state==V2_SLOT_SEALED && part->read==part->written;
            limit=part->segment_limit;
            if(count && current)s_v2_turn_used=true;
            xSemaphoreGive(s_v2_lock);
            if(!current){VF_OP(8);ok=false;break;}
            if(count && !voice_v2_write_pcm(&transport,s_upload_mono,count)){VF_OP(2);ok=false;break;}
            if(count)memset(s_upload_mono,0,count*sizeof(s_upload_mono[0]));
            if(sealed){sent=voice_v2_end_input(&transport,limit);if(!sent)VF_OP(3);break;}
            ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(1));
        }
        if(ok && sent) {
            xSemaphoreTake(s_v2_lock,portMAX_DELAY);
            if(s_v2_capture.generation==generation)(void)v2_capture_release(&s_v2_capture,slot);
            xSemaphoreGive(s_v2_lock);
            ok=voice_v2_fetch_status(&transport)==200;if(!ok)VF_OP(4);
            if(ok && limit) {
                /* Segment acknowledgement is bounded JSON, never an answer. */
                while(!v2_cancelled(&cancel)) {
                    xSemaphoreTake(s_v2_lock,portMAX_DELAY);
                    bool commit=s_v2_capture.commit_pending && s_v2_capture.revision==id.revision;
                    bool next=s_v2_capture.revision>id.revision;
                    xSemaphoreGive(s_v2_lock);
                    if(commit){ok=voice_v2_commit_boundary(&transport) && voice_v2_fetch_status(&transport)==200;if(!ok)VF_OP(5);limit=false;break;}
                    if(next)break;
                    ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(1));
                }
            }
            if(ok && !limit) {
                bool done=v2_receive_with_lease(&transport,&cancel);
                voice_v2_close(&transport);
                if(done || wake_engine_should_cancel(generation))return;
                bool continued=v2_input_continued(generation,id.revision);
                if(!continued){if(cancel.transport_failed)VF_INVALIDATE(&id,&transport,&cancel,6,slot,prepared);return;}
                cancel.response=false;continue;
            }
        }
        voice_v2_close(&transport);
        if(!ok || !sent){VF_INVALIDATE(&id,&transport,&cancel,failure_op,slot,prepared);break;}
    }
}
