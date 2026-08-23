idf_component_register(SRCS "main.c"
                              "max30102.c"
                              "hr_spo2.c"
                              "ble_periph.c"
                              "ws2812.c"
                       INCLUDE_DIRS "."
                       REQUIRES driver nvs_flash bt esp_timer)
