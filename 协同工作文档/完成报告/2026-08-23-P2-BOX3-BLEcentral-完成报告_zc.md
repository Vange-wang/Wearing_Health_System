# zcode 完成报告：P2 BOX-3 BLE central（扫描连接腕部节点 + 数据解析缓存）

- **产出方**：zcode · 2026-08-23
- **任务单**：`协同工作文档/zcode_tasks/2026-08-23-P2-BOX3-BLEcentral-任务单_hm.md`
- **状态**：✅ 实施完成，送 Hermes 审查
- **交付物**：
  - 固件归档：`Code文档/固件/box3_voice_agent/`（源码 + README 联调实录）
  - 源工程：`D:\esp-box\examples\voice_agent\`（build_v1，烧录 COM5）

## 验收标准对照（任务单 §验收，真机联调）

| # | 验收项 | 结果 | 证据（BOX-3 串口日志） |
|---|---|---|---|
| 1 | 扫描 WH-Wrist01 → 连接 → 订阅 notify → 收到 8 字节帧 | ✅ | `命中腕部节点` → `已连接 conn=1` → 服务/特征/CCCD 发现 → `订阅 notify cccd=0x0017 rc=0` → `帧 seq=…` |
| 2 | 帧解析与腕部节点一致 | ✅ | HR/SpO2/conf 真实值（如 `HR=74 SpO2=100 conf=70`），与腕部节点串口同期数据吻合 |
| 3 | seq 递增无跳帧、丢帧检测生效 | ✅ | 连续运行 seq 217→224、1→10 等严格递增 lost=0；腕部节点重启序号归零被标记 lost+=32（如实反映不连续） |
| 4 | 断线自动重连、数据续传、语音不受影响 | ✅ | 拔电 → `连接断开 reason=520` → 后台退避重连（rc=13 失败后 2s 重试）→ 插回 → 自动连接续传；**两次完整语音对话期间 BLE 帧 seq 29-36 不断流** |
| 5 | 重启 BOX-3 开机直连（NVS MAC 生效） | ✅ | BOX-3 重启后日志无按键操作即恢复帧流（seq 从节点侧继续） |
| 6 | 语音链路无回归 | ✅ | 两次完整对话：录音上传 34.8KB/112.6KB PCM、HTTP 200、TTS 播放 17 帧 |

## 实现要点

- **ble_central.c/h**（新增，~400 行）：
  - 扫描匹配按任务单契约：名字前缀 `WH-` + 厂商段 0xFFFF 能力位 bit0/bit1
  - GATT 客户端：发现服务 `7a0b1000-…` → 特征 `7a0b1001-…` → CCCD 0x2902 写 1 订阅
  - 帧解析缓存（seq 丢帧检测/HR-uint16LE/SpO2/conf/flags/battery）+ 临界区保护，`ble_central_get_data()` 供 P3 语音查询
  - NVS `ble_cfg/peer_mac` 存 MAC → 开机直连；断线由独立 `ble_reconn` 任务指数退避重连（2s~30s 封顶），**不进语音首字路径**（红线满足）
- **voice_agent.c** 集成：
  - Boot 双击（`BUTTON_DOUBLE_CLICK`）触发首次扫描；双击窗口放宽 500ms（默认 180ms 人手速不够）
  - **300ms 按住守卫**：短按不发起对话，双击扫描与按住说话手势分离
- **sdkconfig**：开 NimBLE central（BT_ENABLED + ROLE_CENTRAL + MAX_CONNECTIONS=1 + NVS_PERSIST）

## 联调中解决的坑（详见归档 README）

1. IDF 5.2.7 NimBLE API 差异（GATT 发现走独立回调 `ble_gatt_*_fn`，非 GAP 事件；`ble_gap_disc` 需 `disc_params` 结构体；notify 事件为 `NOTIFY_RX`）
2. NimBLE 未同步时扫描 EBUSY（rc=30）→ 交重连任务延迟重试
3. 双击窗口 180ms 过紧 → 放宽 500ms
4. MUTE 键真机无事件 → 改用 Boot 双击 + 按住守卫

## 遗留说明（P2 范围外，如实披露）

- 丢帧计数在节点重启时把序号断崖计入（+32），语义为「不连续计数」而非纯丢帧；如需区分可在后续加 MAC/会话标记
- 状态灯联动（BLE 状态并入 emoji 判定）按任务单约定未做，仅日志输出

## 审查请求

请 Hermes 审查：
1. `Code文档/固件/box3_voice_agent/main/ble_central.c`（扫描匹配/连接流程/GATT 发现/重连状态机）
2. `voice_agent.c` P2 集成部分（双击触发 + 按住守卫 + 初始化位置）
3. 验收日志证据（本报告 + 归档 README 联调实录）

---

*zcode · 2026-08-23 · 后缀 _zc 遵循 agent.md §5.1*
