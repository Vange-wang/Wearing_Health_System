cmake_minimum_required(VERSION 3.16)

# ESP32-C3 SuperMini 腕部节点（MAX30102 心率/血氧 + BLE peripheral）
# P1：指尖式验证，5s/帧 8 字节综合帧
set(IDF_TARGET esp32c3)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ble_wrist_node)
