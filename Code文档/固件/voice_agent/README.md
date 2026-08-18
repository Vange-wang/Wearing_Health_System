# voice_agent 固件归档说明

- **归档日期**：2026-08-19 · 归档人：zcode（BLE 立项 Spec P1 前置，Hermes 审查确认要求）
- **工作源目录**：`D:\esp-box\examples\voice_agent\main\`（ESP-IDF 工程，在此目录编译烧录）

## 版本快照（2026-08-18 18:56，多 WiFi 版）

本归档对应当前真机运行的版本，功能：

1. 按住说话（GPIO0 顶部圆键）：ES7210 双麦录音 → 降混 → chunked 流式上传 raw PCM → 收长度前缀 WAV 帧 → ES8311 播放（`D:\workbuddy_project\项目\可穿戴健康辅助系统\voice-bridge`，voicebridge.local:8710）
2. mDNS 客户端解析 voicebridge.local
3. **多 WiFi 自动切换**（Spec `2026-08-18-多WiFi自动切换-spec_hm.md`）：NVS 三组凭据（v2/2702/L1122S，v2 优先）+ 开机扫描 + 断开重连 + 指数退避——**代码完成，三组切换真机验证待回家补**（见 `Code文档/2026-08-18-网络切换与TTS修复-自测报告_wb.md` §遗留）

## 文件

| 文件 | 说明 |
|---|---|
| `voice_agent.c` | 固件源码（489 行，单文件） |
| `CMakeLists.txt` | 组件注册 |
| `idf_component.yml` | 依赖（espressif/mdns ^1.0.0） |

## 编译烧录

按 `Code文档/ESP32固件-编译烧录配方.md`（必胜版）：IDF v5.2.7 环境 + 全新 build 目录 + COM5。依赖 BSP：esp-box-3 锁 1.2.0~2。

## 纪律

- 固件改动后**先更新本归档再编译烧录**（工作目录是编译现场，git 仓库是版本真相）；
- BLE central（P2）将在 `voice_agent.c` 基础上扩展，BLE 数据帧契约见 `规划文档/技术验证/2026-08-19-BLE数据帧协议_zc.md`。
