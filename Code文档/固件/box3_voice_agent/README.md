# BOX-3 语音终端固件（voice_agent + BLE central，P2/P3/P4）

## 概述

ESP32-S3-BOX-3 语音终端固件：v0.4 语音链路（按键说话 → voice-bridge 流式 ASR/TTS）+ **P2 BLE central**（连接腕部节点 WH-Wrist01，接收综合帧并缓存）+ **P3 数据上报**（有效帧 POST `/api/v1/health/data`）+ **P4 预警空闲轮询播报**（30s/次 GET `/api/v1/health/alert`，不打断对话）。

## 硬件与烧录

| 项 | 值 |
|---|---|
| 主控 | ESP32-S3（BOX-3，16MB Flash + 8MB PSRAM） |
| 烧录端口 | **COM5**（`python D:\esp-box\build_voice.py`，默认 build 后自动烧录） |
| 构建目录 | `build_v1/` |
| 按键 | Boot（GPIO0）：按住说话 / **双击触发 BLE 首次扫描**；顶部 MUTE（GPIO1）暂未用 |

## 软件架构（本次 P2/P3 新增）

- `main/ble_central.c/h` — **BLE central（P2 新增）**：
  - 扫描匹配：名字前缀 `WH-` + 厂商段 0xFFFF 能力位 bit0/bit1（与 P1 `ble_periph.c` 契约对齐）
  - 连接 → 服务发现（`7a0b1000-…`）→ 特征发现（`7a0b1001-…`）→ CCCD 订阅 notify
  - 8 字节帧解析缓存（seq 丢帧检测 / HR-uint16LE / SpO2 / conf / flags / battery），临界区保护，供语音任务查询
  - NVS 存对端 MAC → **开机直连** + 断线后台重连（指数退避 2s~30s，独立任务，不阻塞语音）
- **P3 数据上报（`ble_central.c` 内 upload_task）**：
  - 有效帧（flags bit0/bit1 任一置位）触发上报：`POST http://voicebridge.local:8710/api/v1/health/data`，JSON `{"hr":N,"spo2":N,"seq":N}`，**无效字段传 null**（服务端 Pydantic 可空）
  - **关键规则**：无手指帧（flags=0x00）**不上报**——服务端 `update()` 会刷新新鲜度时间戳，若连无效帧都传，摘指后「暂时中断」永远不会触发
  - 失败静默：重试 1 次（间隔 2s），连续失败仅首条/每 12 条打一条 WARN；首次成功与恢复打 INFO
  - 独立 `ble_upload` 任务（信号量由 cache_frame 驱动），**不进语音首字路径**（红线满足）
- **P4 预警空闲轮询播报（`voice_agent.c` alert_poll_task）**：
  - 每 30s（Spec 30~60s）GET `http://voicebridge.local:8710/api/v1/health/alert`，仅当 `s_wifi_up && !s_recording && !s_talk_active` 才轮询——**不打断对话**
  - 200 → 逐帧解析（长度前缀 WAV，复用语音帧协议）→ play_wav 播放（可被按键打断，`s_cancel` 机制复用）
  - 204/网络失败 → 静默继续；任务优先级 4，独立于语音首字路径
- `main/voice_agent.c` — v0.4 语音链路 + P2 集成：
  - Boot 双击（BUTTON_DOUBLE_CLICK）触发首次扫描；双击窗口放宽至 500ms（`CONFIG_BUTTON_SHORT_PRESS_TIME_MS=500`，默认 180ms 人手速不够）
  - **300ms 按住守卫**：按住不足 300ms 视为单击/双击手势，不发起对话（防双击触发扫描时产生空 HTTP 请求）
  - BLE central 初始化在 app_main 尾部（NimBLE 主机任务 + ble_reconn/ble_upload 任务，均独立于语音首字路径）

## 关键配置（sdkconfig.defaults 新增）

```
CONFIG_BT_ENABLED=y
CONFIG_BT_NIMBLE_ENABLED=y
CONFIG_BT_NIMBLE_ROLE_CENTRAL=y
CONFIG_BT_NIMBLE_ROLE_PERIPHERAL=n
CONFIG_BT_NIMBLE_MAX_CONNECTIONS=1
CONFIG_BT_NIMBLE_NVS_PERSIST=y
CONFIG_BUTTON_SHORT_PRESS_TIME_MS=500
```

> 注意：sdkconfig 曾关过 BT（`CONFIG_BT_ENABLED is not set`），新增 defaults 后需删除 sdkconfig 重新生成，否则配置不生效。

## 已解决的坑（P2 联调实录，2026-08-23）

1. **IDF 5.2.7 NimBLE API 差异**：GATT 客户端发现用独立回调（`ble_gatt_disc_svc_fn`/`chr_fn`/`dsc_fn`，完成标志 `error->status == BLE_HS_EDONE`），不是 GAP 事件；`ble_gap_disc` 需 `struct ble_gap_disc_params`（filter_policy 用 `BLE_HCI_SCAN_FILT_NO_WL`）；notify 接收事件为 `BLE_GAP_EVENT_NOTIFY_RX`
2. **扫描 EBUSY（rc=30）**：NimBLE 主机同步完成前发起扫描会失败，交重连任务延迟重试
3. **双击判定窗口 180ms 太紧**：人手速双击通常 300-500ms，需放宽 `CONFIG_BUTTON_SHORT_PRESS_TIME_MS=500`
4. **MUTE 键不可靠**（真机按压多次无事件）：改用 Boot 键双击触发扫描，加 300ms 按住守卫区分说话/双击

## 联调验收（2026-08-23 真机，任务单 6 项全过）

1. ✅ 双击 Boot → 扫描 → 命中 WH-Wrist01 → 连接 → 订阅 notify → 收到 8 字节帧
2. ✅ 帧解析与腕部节点串口一致（HR/SpO2 真实值）
3. ✅ seq 连续无跳帧（lost=0）；节点重启的序号断崖被丢帧检测如实标记
4. ✅ 腕部节点断电 → reason=520 断线 → 后台指数退避重连 → 通电后自动连回续传；对话期间 BLE 帧不断流（语音不阻塞 BLE，BLE 不阻塞语音）
5. ✅ 重启 BOX-3 → NVS MAC 开机直连（无需按键）
6. ✅ 语音无回归：两次完整对话（HTTP 200，TTS 播放 17 帧）

## 归档信息

- 归档日期：2026-08-23 · 归档人：zcode
- 源目录：`D:\esp-box\examples\voice_agent\`
- 对应任务单：`协同工作文档/zcode_tasks/2026-08-23-P2-BOX3-BLEcentral-任务单_hm.md`、`2026-08-23-P3-数据流与语音查询-任务单_hm.md`
