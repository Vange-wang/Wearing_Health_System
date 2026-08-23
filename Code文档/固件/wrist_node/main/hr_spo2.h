#pragma once
#include <stdint.h>

/* 心率/血氧算法（P1：峰峰间隔法 + R 比率法） */

typedef struct {
    uint16_t heart_rate;   /* BPM，0=无效 */
    uint8_t  spo2;         /* %，0=无效 */
    uint8_t  confidence;   /* 0-100 */
    uint8_t  flags;        /* bit0=HR有效 bit1=SpO2有效 bit2=运动伪影 */
} hr_spo2_result_t;

/* 喂原始样本（采样任务调用，速率按实测自适应，克隆芯片寄存器表可能不准） */
void hr_spo2_push(uint32_t ir, uint32_t red);

/* 用最近 10s 滑动窗口计算（5s 上报任务调用） */
hr_spo2_result_t hr_spo2_compute(void);
