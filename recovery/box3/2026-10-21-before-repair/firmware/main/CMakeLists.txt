idf_component_register(
    SRCS
        "voice_agent.c"
        "voice_v2_transport.c"
        "voice_v2_capture.c"
        "service_origin.c"
        "service_discovery.c"
        "discovery_hint.c"
        "discovery_protocol.c"
        "mic4_layout.c"
        "display_dispatch.c"
        "dns_ip_probe.c"
        "http_body_dynamic.c"
        "caption_ui.c"
        "caption_text.c"
        "box_caption_font.c"
        "health_json.c"
        "audio_session.c"
        "wake_engine.c"
        "wake_ack.c"
        "barge_in_gate.c"
        "duplex_audio.c"
        "wav_stream.c"
        "ble_central.c"
        "credential_store.c"
        "device_auth_client.c"
    INCLUDE_DIRS
        "")

# This fixed diagnostic candidate performs public fake-vector checks once at
# boot. Root may explicitly build OFF as a separately hashed variant.
option(BOX_DISCOVERY_SELF_TEST "Run public discovery KDF/MAC boot selftest" ON)
if(BOX_DISCOVERY_SELF_TEST)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE DEVICE_AUTH_DISCOVERY_SELF_TEST=1)
    target_sources(${COMPONENT_LIB} PRIVATE "discovery_origin_selftest.c")
endif()

# 屏幕 emoji 状态显示：把 ../spiffs 目录打包进 storage 分区（与 image_display 同流程）
spiffs_create_partition_image(storage ../spiffs FLASH_IN_PROJECT)

# Root-only diagnostic build; default OFF leaves the normal audio path unchanged.
option(VOICE_WAKE_DIAGNOSTICS "Numeric passive wake diagnostics" OFF)
if(VOICE_WAKE_DIAGNOSTICS)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE VOICE_WAKE_DIAGNOSTICS=1)
endif()

option(VOICE_V2_FAILURE_DIAGNOSTICS "Numeric v2 failure diagnostics" OFF)
if(VOICE_V2_FAILURE_DIAGNOSTICS)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE VOICE_V2_FAILURE_DIAGNOSTICS=1)
endif()

option(VOICE_PUBLIC_PCM_INJECTION "Public REAL_MODEL three-question diagnostic" OFF)
if(VOICE_PUBLIC_PCM_INJECTION)
    if(NOT VOICE_WAKE_DIAGNOSTICS OR NOT VOICE_V2_FAILURE_DIAGNOSTICS)
        message(FATAL_ERROR "Public source requires both existing numeric diagnostic gates")
    endif()
    target_compile_definitions(${COMPONENT_LIB} PRIVATE VOICE_PUBLIC_PCM_INJECTION=1)
    target_sources(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_LIST_DIR}/public_pcm_feed.c")
endif()
