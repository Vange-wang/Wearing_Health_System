# voice_agent 固件归档说明

- **归档日期**：2026-08-19 · **更新**：2026-08-20（zcode，屏幕 emoji 状态显示）
- **工作源目录**：`D:\esp-box\examples\voice_agent\main\`（ESP-IDF 工程，在此目录编译烧录）

## 版本快照（2026-08-20，屏幕 emoji 版）

本归档对应当前真机运行的版本，功能：

1. 按住说话（GPIO0 顶部圆键）：ES7210 双麦录音 → 降混 → chunked 流式上传 raw PCM → 收长度前缀 WAV 帧 → ES8311 播放（`voice-bridge`，voicebridge.local:8710）
2. mDNS 客户端解析 voicebridge.local
3. **多 WiFi 自动切换**（Spec `2026-08-18-多WiFi自动切换-spec_hm.md`）：NVS 三组凭据（v2/2702/L1122S，v2 优先）+ 开机扫描 + 断开重连 + 指数退避
4. **屏幕 emoji 状态显示**（Spec `2026-08-19-状态灯与联网搜索-实现方案_zc.md` 需求 1）：LVGL + SPIFFS 4 态 emoji（😄/😵/🤐/🌚），30s 轮询 `/api/v1/health` + WiFi 状态即时重判，WiFi 断时用 vb 缓存

> ⚠️ **密码已脱敏**：`voice_agent.c` 里 `DEFAULT_WIFI_CREDS` 的三组密码已改为占位符（`WIFI_PASS_V2`/`WIFI_PASS_HOME_1`/`WIFI_PASS_HOME_2`），推 GitHub 前按 Vange 要求脱敏。**实际部署烧录前需在 `D:\esp-box\examples\voice_agent\main\voice_agent.c`（工作源）填入真实密码**——本归档仅供代码审查，不做直接烧录。

## 文件

| 文件 | 说明 |
|---|---|
| `voice_agent.c` | 固件源码（含屏幕 emoji 状态显示） |
| `CMakeLists.txt` | 组件注册 + `spiffs_create_partition_image` 打包 emoji PNG |
| `idf_component.yml` | 依赖（espressif/mdns ^1.0.0） |
| `spiffs/` | 4 个 emoji PNG（😄u1f604 / 😵u1f635 / 🤐u1f910 / 🌚u1f31a，128×128 RGBA） |

## 编译烧录

按 `Code文档/ESP32固件-编译烧录配方.md`（必胜版）：IDF v5.2.7 环境 + 全新 build 目录 + COM5。依赖 BSP：esp-box-3 锁 1.2.0~2。emoji PNG 用 Segoe UI Emoji 字体生成（个人毕设演示用途，开源/商用需换 Noto/Twemoji）。

## 纪律

- 固件改动后**先更新本归档再编译烧录**（工作目录是编译现场，git 仓库是版本真相）；
- BLE central（P2）将在 `voice_agent.c` 基础上扩展，BLE 数据帧契约见 `规划文档/技术验证/2026-08-19-BLE数据帧协议_zc.md`。
