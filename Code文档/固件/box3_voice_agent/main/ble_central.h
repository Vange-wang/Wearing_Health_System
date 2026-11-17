#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* BLE central（P2）：最多连接两个独立腕部节点，订阅综合帧 notify 并缓存
 * 协议契约：规划文档/技术验证/2026-08-19-BLE数据帧协议_zc.md
 * 8 字节帧：seq(0)/flags(1)/HR-uint16LE(2-3)/SpO2(4)/conf(5)/battery(6)/reserved(7)
 * 特征：7a0b1001-8c1d-4e2f-9a3b-5c6d7e8f9a0b（notify，随 P1 ble_periph.c 对齐） */

typedef struct {
    uint8_t  seq;        /* 最新帧序号 */
    uint8_t  flags;      /* bit0=HR有效 bit1=SpO2有效 bit2=运动伪影 */
    uint16_t hr;         /* BPM */
    uint8_t  spo2;       /* % */
    uint8_t  conf;       /* 0-100 */
    uint8_t  battery;    /* % */
    uint32_t ts_ms;      /* 最近一帧时间戳（开机起 ms） */
    uint32_t lost;       /* 累计丢帧数（seq 不连续） */
    bool     valid;      /* 是否收到过有效帧 */
    uint64_t source_generation; /* real BLE connection lifecycle */
    uint64_t source_index;      /* unfolded seq within this connection */
    uint64_t source_received_us; /* first independent frame arrival, never retry time */
    uint64_t upload_generation; /* selected output stream, not BLE generation */
    uint32_t node_token;
    uint8_t node_slot;
} ble_health_t;
typedef struct {
    uint8_t address_type,address[6],phase;
    uint16_t conn_handle;
    uint32_t token;
    bool selected;
    uint64_t last_good_us,upload_generation;
    ble_health_t latest;
} ble_node_snapshot_t;
bool ble_central_get_node_data(unsigned slot,ble_node_snapshot_t *out);

/* 初始化 NimBLE central（含 NVS 读 MAC、创建重连任务；NVS 须已初始化） */
esp_err_t ble_central_init(void);

/* 唤醒后台发现：有空位才扫描；已满两个连接则忽略 */
void ble_central_start_scan(void);

/* 连接状态（日志/调试用） */
bool ble_central_is_connected(void);

/* 读已选择输出缓存（固定大小拷贝，不遍历节点；无来源时false） */
bool ble_central_get_data(ble_health_t *out);
