# zcode 任务单：P2 BOX-3 BLE central（扫描连接腕部节点 + 数据解析缓存）

- **下达方**：Hermes（审查）· 2026-08-23 · P1 已 REVIEW_PASS 闭环
- **状态**：待 zcode 实施
- **依据**：`规划文档/Spec文档/2026-08-19-BLE健康监测与家庭预警-立项-spec_hm.md` P2 路径 + `规划文档/技术验证/2026-08-19-BLE数据帧协议_zc.md`（P1 已按此实现，两端契约已对齐）

## 目标（Spec P2）

BOX-3 加 BLE central：扫描连接腕部节点（WH-Wrist01），接收综合帧 + 解析缓存 → **BOX-3 能拿到心率/血氧**。

## 契约（协议文档 §4/§5，P1 已按此实现，BOX-3 必须对齐）

| 项 | 值 |
|---|---|
| 广播名 | `WH-Wrist01`（前缀 `WH-` + 厂商能力位 0xFFFF: bit0 心率/bit1 血氧） |
| 连接间隔 | 100~200ms；slave latency 4；supervision timeout 4s |
| 配对 | Just Works 不加密；不绑定（bondless） |
| 重连 | BOX-3 侧 NVS 存对端 MAC → 断线周期扫描指定 MAC 重连（不阻塞语音任务） |
| 主通道 | 自定义综合帧特征 `7a0b1001-8c1d-4e2f-9a3b-5c6d7e8f9a0b`（notify） |
| 帧格式 | 8 字节：seq(0)/flags(1)/HR-uint16LE(2-3)/SpO2(4)/conf(5)/battery(6)/reserved(7) |
| MTU | 默认 23 即可（帧仅 8 字节，无需 MTU 交换） |

## 实施内容（BOX-3 固件 `D:\esp-box\examples\voice_agent\`）

1. **NimBLE central 集成**：voice_agent.c 增加 BLE central 任务（与 WiFi/语音任务并行，不阻塞语音）；参考 `D:\esp-box\examples\ble_wrist_node\`（若为 peripheral 例程则需反转角色）；
2. **扫描与匹配**：按键触发首次扫描 → 按名字前缀 `WH-` + 能力位匹配 → 连接成功 → NVS 存 MAC；
3. **订阅与解析**：连接后订阅综合帧特征 notify → 8 字节帧解析（seq 丢帧检测/flags 有效性/HR/SpO2/conf）→ 缓存最新值（带时间戳，供 P3 语音查询）；
4. **断线重连**：检测断开 → 周期扫描指定 MAC 重连，**不阻塞语音任务**（后台任务）；首次连接后开机直连；
5. **状态灯联动**：BLE 连接状态并入现有 4 态 emoji 判定？——**先不做**（P2 范围外），仅在日志/调试输出连接状态；
6. **协议文档**：两端 UUID 已对齐（P1 固件 `ble_periph.c` 实测确认），**改动需两端同步**。

## 验收（Spec P2，与 P1 腕部节点联调）

1. BOX-3 扫描到 WH-Wrist01 → 连接成功（日志可见）→ 订阅 notify → 收到 8 字节帧；
2. 帧解析正确：HR/SpO2/conf 与腕部节点上报一致（腕部节点串口日志可对照）；
3. seq 递增无跳帧（丢帧检测生效）；flags 有效性处理正确；
4. 断线（腕部节点断电/关广播）→ BOX-3 自动周期重连，恢复后数据续传；**语音对话不受影响**（BLE 任务不阻塞）；
5. 重启 BOX-3 → 开机直连（NVS MAC 生效，无需重新按键扫描）；
6. 全量回归：语音链路（ASR/TTS/对话）无回归。

## 备注

- 与 P1 腕部节点联调：腕部节点当前固件（`Code文档/固件/wrist_node/`）即测试对端，无需改动；
- 首字红线（agent.md 最高铁律）：BLE central 扫描/重连全部后台任务，**不得进入语音首字路径**；
- 产出后送 Hermes 审查（deepseek-v4-pro）。

*Hermes（deepseek-v4-pro）· 2026-08-23 · 后缀 _hm 遵循 agent.md §5.1*
