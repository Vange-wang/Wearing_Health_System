# P2 BOX-3 BLE central 完成报告审查

- **审查方**：Hermes（deepseek-v4-pro）· 2026-08-23
- **对象**：`协同工作文档/完成报告/2026-08-23-P2-BOX3-BLEcentral-完成报告_zc.md`（zcode）
- **依据**：`zcode_tasks/2026-08-23-P2-BOX3-BLEcentral-任务单_hm.md`（Hermes 下达）
- **结论**：**REVIEW_PASS**——验收 6 项全部满足（真机日志证据）、契约与协议文档逐项对齐、首字红线满足。遗留 2 项 P2 范围外不阻塞，P3 可开工。

---

## 一、验收对照（任务单 §验收）

| # | 验收项 | 判定 | 核查 |
|---|---|---|---|
| 1 | 扫描 WH-Wrist01 → 连接 → 订阅 → 收 8 字节帧 | ✅ | 代码：`TARGET_NAME_PREFIX "WH-"` + 厂商段 0xFFFF 能力位匹配；GATT 发现 combo 特征 → CCCD 订阅；notify 事件 `BLE_GAP_EVENT_NOTIFY_RX`（README 有日志链） |
| 2 | 帧解析与腕部节点一致 | ✅ | `ble_central.c:126-130` 逐字段：seq/flags/HR-uint16LE/SpO2/conf/battery，与协议 §2 完全一致 |
| 3 | seq 递增无跳帧 + 丢帧检测 | ✅ | `:136-139` 8-bit 回绕差值 >1 计丢帧；如实披露节点重启序号断崖计入 lost（遗留项 #1） |
| 4 | 断线重连、续传、语音不阻塞 | ✅ | `:361-369` 指数退避 2s→30s 封顶，独立任务；README：reason=520 断线 → 重连 → 续传；**对话期间 BLE 帧不断流** |
| 5 | 开机直连（NVS MAC） | ✅ | `NVS_KEY_MAC "peer_mac"` + 开机直连流程（README 实测） |
| 6 | 语音无回归 | ✅ | 两次完整对话：PCM 34.8/112.6KB、HTTP 200、TTS 17 帧 |

## 二、代码质量核查

| 关注点 | 判定 |
|---|---|
| 契约常量（WH-/0xFFFF/7a0b1000-1001/CCCD 0x2902）与协议文档、P1 固件 `ble_periph.c` 三端一致 | ✅ |
| 双击触发扫描（`BUTTON_DOUBLE_CLICK`）+ 300ms 按住守卫（防双击误触发起空对话） | ✅ 手势分离设计合理 |
| 双击窗口放宽 500ms（180ms 人手速不够，实测修正） | ✅ |
| 重连状态机：EBUSY（rc=30）延迟重试 + 指数退避，独立 `ble_reconn` 任务 | ✅ |
| **首字红线**（agent.md 最高铁律）：BLE 扫描/重连均在独立任务，不进语音首字路径；README 明确"独立于语音首字路径" | ✅ |
| IDF 5.2.7 NimBLE API 差异（GATT 独立回调/`disc_params`/NOTIFY_RX）已适配 | ✅ |

## 三、遗留（P2 范围外，如实披露，不阻塞）

1. 丢帧计数在节点重启时计入序号断崖（语义为"不连续计数"）→ 后续可加 MAC/会话标记区分；
2. 状态灯联动（BLE 状态并入 emoji 判定）按任务单约定未做，仅日志——**建议 P3 顺带评估**（用户感知：腕部节点断连时屏幕应能反映）。

## 四、结论

**REVIEW_PASS**。P2 闭环：BOX-3 已能自动连接腕部节点、订阅并解析 8 字节帧、断线自动重连、开机直连、语音零影响。三端契约（协议文档 / P1 peripheral / P2 central）完全对齐。**P3（数据流 + 语音查询 + DATA 路由）可开工**。

---

*Hermes（deepseek-v4-pro）· 2026-08-23 · 审查报告遵循 agent.md §5.1（_hm 后缀）*
