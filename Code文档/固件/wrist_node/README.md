# 腕部节点固件（ESP32-C3 + MAX30102）

## 概述

BLE 腕部健康监测节点，采集心率和血氧数据，通过 BLE 广播发送到 BOX-3 语音终端。

## 硬件配置

| 项 | 值 |
|---|---|
| 主控 | ESP32-C3 SuperMini |
| 传感器 | MAX30102（心率+血氧） |
| I2C 接线 | SDA=GPIO4, SCL=GPIO5 |
| 供电 | VIN→3V3, GND→GND |
| LED 电流 | 0x0F（3mA），拆盖后光路强需降电流防饱和 |
| 采样率 | 名义 100Hz（SPO2_CONFIG=0x26，FIFO_CONFIG=0x0F 关闭采样平均）；算法按实测速率自适应 |
| 烧录端口 | COM6 |

## 软件架构

- `main.c` — 主程序（采样/上报/LED 三个 FreeRTOS 任务）
- `max30102.c` — **软件 I2C（bit-bang）**驱动 + 总线自愈恢复
- `hr_spo2.c` — 心率（峰峰间隔法）+ 血氧（R 比率，MAXREFDES117 拟合）
- `ble_periph.c` — NimBLE peripheral（心率 0x180D + 自定义综合帧 + 设备信息）
- `ws2812.c` — GPIO8 RGB 状态灯（RMT 驱动）

## 构建与烧录

```bash
# 编译
python D:\esp-box\build_wrist.py

# 烧录
python D:\esp-box\build_wrist.py --flash
```

## 已解决的硬件坑（新模块复现时参考）

1. **MLED_CTRL1 寄存器（0x11）必须显式写 0x21**（SLOT1=RED, SLOT2=IR）——复位后默认 0x00，槽位全禁用→FIFO 永远空
2. **SPO2_CONFIG ADC 量程 0x47（4096nA）** 而非 0x27（2048nA），否则量程不够
3. **LED 电流**：拆掉保护盖后光路强，7.2mA（0x24）会让 IR 饱和削顶（ADC 值 262143），降到 3mA（0x0F）
4. **IO_MUX FUN_IE**：IDF 5.2 的 `gpio_config()` 对输出模式会关闭 IO_MUX 输入使能（FUN_IE），导致 `gpio_get_level` 恒读 0（ACK 假阳性）。必须在 `gpio_config` 后调 `gpio_ll_input_enable` 重开输入
5. **硬件 I2C 驱动不可靠**：IDF 5.2 新 `i2c_master` 驱动在设备 NACK 时有无超时忙等缺陷（WDT 饿死）；legacy 驱动恢复后 `i2c_driver_install` 反复失败。最终用**软件 I2C（bit-bang）**彻底解决
6. **MAX30102 LED 小板是排针/焊接连接**，拆保护盖时容易碰松，按压可能导致焊点断裂
7. **SMP_AVE 会分频 FIFO 速率**：FIFO_CONFIG 的 SMP_AVE=4 会把 FIFO 更新速率除以 4（50Hz→12.5Hz），而算法原本按 100Hz 计算 BPM/峰间距，8 倍偏差。修复：SMP_AVE=0（不平均）+ SR=100Hz（SPO2_CONFIG=0x26，数据手册 Table 6 确认 001=100sps）
8. **克隆芯片实测速率不可信**：本模块一度实测 ~200Hz（数据手册应为 100Hz）。固件算法已改为**按实测速率自适应**（时间戳测速率 → BPM=60×rate/峰间距），串口 `rate=` 打点即真相，换模块不再需要改代码
9. **LED 小板 RED/IR 焊盘锡桥会偷走红灯电流**（2026-08-23 新模块复现）：IR VF=1.4V < RED VF=2.1V，节点短路时电流全走红外路，红灯不亮（redDC≈69 而 irDC≈21k）。拔掉 IR 灯后红灯亮、两通道均 ≈45k。修复：检查 LED 小板焊点，清理 RED/IR 之间的锡桥后接回

## BLE 广播协议

广播名：`WH-Wrist01`

服务布局：
- 心率服务（0x180D）：心率测量特征（0x2A37）
- 自定义综合帧服务：心率+血氧+电池+状态
- 设备信息服务：厂商名+型号+序列号

详见 `规划文档/技术验证/2026-08-19-BLE数据帧协议_zc.md`

## 当前状态

- ✅ 软件全部完成并验证通过（BLE 广播/GATT/心率血氧算法）
- ✅ 新 MAX30102 模块实测通过（2026-08-23）：硬件误接线问题已定位排除，双 LED 正常，采样率 100Hz
- ✅ 指尖血氧仪校准 3 轮对照通过：SpO2 偏差 ≤+2%（±3% 内），HR 偏差 ±6 bpm 内
- ⚠️ 遗留：HR 峰检测对手指微动敏感（静置时 conf 60-85，微动瞬间 HR 偶发跳变），后续可优化（提高 LED 电流/滤波）

## 归档信息

- 归档日期：2026-08-22（初版）/ 2026-08-23（更新：采样率自适应、校准验证）
- 归档人：zcode
- 源目录：`D:\esp-box\examples\ble_wrist_node\`
