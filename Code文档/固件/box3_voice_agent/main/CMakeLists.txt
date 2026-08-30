idf_component_register(
    SRCS
        "voice_agent.c"
        "audio_session.c"
        "wav_stream.c"
        "ble_central.c"
        "credential_store.c"
        "device_auth_client.c"
    INCLUDE_DIRS
        "")

# 屏幕 emoji 状态显示：把 ../spiffs 目录打包进 storage 分区（与 image_display 同流程）
spiffs_create_partition_image(storage ../spiffs FLASH_IN_PROJECT)
