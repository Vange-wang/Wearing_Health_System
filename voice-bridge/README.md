# voice-bridge（语音桥服务 v0.3）

PC 端本地 HTTP 语音服务：**Hermes 的语音前端**——接收音频 → VAD → ASR → **Hermes（流式）** → 分句 TTS → 长度前缀帧流返回。voice-bridge 只负责「听」和「说」，「想」交给 Hermes（与微信共用同一 profile 的 persistent memory + skills）。

## Hermes 侧准备（v0.3 新增）

voice-bridge 通过 Hermes gateway 内置的 OpenAI 兼容 API Server 接入（`POST /v1/chat/completions`）。

```bash
# 1. 启用 API Server（Hermes CLI）
hermes config set API_SERVER_ENABLED true
hermes config set API_SERVER_KEY <强密钥>

# 2. 语音通道工具集裁剪（A4）：编辑 ~/.hermes/config.yaml，
#    platform_toolsets 新增 api_server 键（weixin/cli 键不动）：
#    platform_toolsets:
#      api_server: [memory, skills, session_search, web]

# 3. 重启 gateway 生效（微信 bot 会短暂中断数秒）

# 4. 把同一个 API_SERVER_KEY 写进 voice-bridge/.env：
#    HERMES_API_KEY=<同一个密钥>
```

- 健康检查：`curl -H "Authorization: Bearer <key>" http://127.0.0.1:8642/health`
- 按 platform 裁剪实测结论：`../规划文档/技术验证/2026-08-15-A4-按platform裁剪工具集-实测.md`

## 环境准备

```bash
# 1. 建 venv（Python 3.11）
C:\Users\86166\AppData\Local\Programs\Python\Python311\python.exe -m venv venv

# 2. 装依赖（运行依赖 + 冒烟测试依赖）
venv\Scripts\python -m pip install -r requirements.txt
venv\Scripts\python -m pip install -r requirements-dev.txt   # 跑测试才需要

# 3. 放模型（不入库，gitignore）
models/
  sherpa-onnx-sense-voice-zh/      # ASR：SenseVoice（model.int8.onnx + tokens.txt）
  piper/zh_CN-huayan-medium.onnx + .onnx.json   # TTS 兜底

# 4. Hermes API Server key（不入库）：复制到 .env
#    HERMES_API_KEY=<与 Hermes 侧 API_SERVER_KEY 相同>
```

## 启动

```bash
venv\Scripts\python run.py      # 监听 0.0.0.0:8710
```

## 接口

| 接口 | 说明 |
|---|---|
| `GET /api/v1/health` | `{"status":"ok","asr":"ready","tts":{...},"vad":"enabled","llm":"hermes"}` |
| `POST /api/v1/voice/chat` | （v0.1 保留，非流式）multipart `audio`=WAV → 完整 WAV bytes + `X-Timing` |
| `POST /api/v1/voice/chat/stream` | （流式）multipart `audio`=WAV → 长度前缀帧流 |

## 流式帧协议（v0.2 起不变）

- 每帧 = `[4 字节大端 uint32 长度 N]` + `[N 字节 = 一句完整 WAV（16kHz/16bit/mono）]`；EOF = 响应体结束；8MB 帧长守卫
- 响应头：`Content-Type: application/octet-stream` + `X-Audio-Framing: wav-length-prefixed` + `X-Timing`

## 分段计量（v0.3 新增，Spec §4）

`X-Timing` 含：`open_ms` / `asr_ms` / `llm_ttft_ms` / `tts_first_ms` / **`tool_ms`（工具期，如实上报不卡线）** / **`answer_open_ms`（答案期 = open_ms - tool_ms，验收卡 ≤1600ms）** / `llm_backend`。纯闲聊 tool_ms=0。

## 冒烟测试

```bash
venv\Scripts\python -m pytest tests/ -v        # v0.2 回归 + v0.3 套件
# v0.3 真实集成（T4~T6/T8）：需 HERMES_E2E=1 + HERMES_API_KEY + API Server 运行
```

## 说明

- ASR：sherpa-onnx + SenseVoice（本地推理，批式）；VAD：能量门限（静音拦截 → 400 no_speech）
- LLM：**Hermes API Server**（v0.3 A1 彻底替换 DeepSeek，无兜底路径）；与微信共用 persistent memory（每轮独立 session，跨轮记忆靠 persistent memory，A3）；SSE 工具指示事件已过滤不进分句器
- TTS：edge-tts 主（晓晓）/ piper 离线兜底。**edge 现网 403 → piper 实际承载**；已知宕机时短路直走 piper；health 如实上报
- Spec：`../规划文档/Spec文档/2026-08-15-语音桥-spec-v0.3.md`；自测报告：`../Code文档/v0.3自测报告.md`

## 已知环境修复（迁移/重装必读）

### piper espeak-ng-data（junction）【OI-005】

piper-tts 1.6.0 Windows wheel 的 espeak-ng-data 查找用了编译机硬编码路径
`D:\a\piper1-gpl\piper1-gpl\_skbuild\win-amd64-3.9\cmake-build\espeak_ng-install\share`。
本机已用目录联接修复；**迁移机器/重建 venv 后需重建**（PowerShell）：

```powershell
$hard = "D:\a\piper1-gpl\piper1-gpl\_skbuild\win-amd64-3.9\cmake-build\espeak_ng-install\share"
New-Item -ItemType Directory -Force -Path $hard | Out-Null
New-Item -ItemType Junction -Path "$hard\espeak-ng-data" -Target "D:\<项目>\voice-bridge\venv\Lib\site-packages\piper\espeak-ng-data"
```

### edge-tts 输出格式（vendor patch）【OI-006】

edge-tts 6.1.x 固定输出 24kHz mp3，Spec 要求返回 16kHz WAV。
本机已 patch `venv\Lib\site-packages\edge_tts\communicate.py` 第 339 行
`outputFormat` 为 `riff-16khz-16bit-mono-pcm`。**重装 edge-tts 会覆盖**，需重新 patch：

```bash
venv\Scripts\python -c "import pathlib; p=pathlib.Path('venv/Lib/site-packages/edge_tts/communicate.py'); t=p.read_text(encoding='utf-8'); t=t.replace('audio-24khz-48kbitrate-mono-mp3','riff-16khz-16bit-mono-pcm'); p.write_text(t, encoding='utf-8')"
```

> edge 恢复评估（OI-004，2026-08-15 已出结论）：edge-tts 7.2.8 实测 403 已修复但首音频 0.9~1.2s 劣于 piper 0.2s，**维持 piper 承载**；恢复为可选项，见 `../规划文档/技术验证/2026-08-15-edge-tts恢复评估-OI004.md`。
