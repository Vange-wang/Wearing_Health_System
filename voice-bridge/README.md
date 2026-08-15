# voice-bridge（语音桥服务 v0.2）

PC 端本地 HTTP 语音服务：接收音频 → VAD → ASR → DeepSeek（流式）→ 分句 TTS → 长度前缀帧流返回。开发板（ESP32-S3）与大脑之间的语音通道（v0.2 暂不接 Hermes）。

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

# 4. DeepSeek key（不入库）：复制到 .env
#    DEEPSEEK_API_KEY=sk-xxx
```

## 启动

```bash
venv\Scripts\python run.py      # 监听 0.0.0.0:8710
```

## 接口

| 接口 | 说明 |
|---|---|
| `GET /api/v1/health` | `{"status":"ok","asr":"ready","tts":{"configured_primary":"edge","active_engine":"piper","fallback_reason":"edge_403"},"vad":"enabled"}` |
| `POST /api/v1/voice/chat` | （v0.1 保留，非流式）multipart `audio`=WAV → 完整 WAV bytes + `X-Timing` |
| `POST /api/v1/voice/chat/stream` | （v0.2 新增，流式）multipart `audio`=WAV → 长度前缀帧流 |

## 流式帧协议（v0.2）

- 响应 `Transfer-Encoding: chunked`，应用层分帧（长度前缀帧）：
  - 每帧 = `[4 字节大端 uint32 长度 N]` + `[N 字节 = 一句完整 WAV（RIFF + 16kHz/16bit/mono PCM）]`
  - 客户端循环：读 4 字节长度 → 读 N 字节 → 播放该句
  - EOF = HTTP 响应体结束（无哨兵帧）；最大帧长 8MB 服务端守卫
- 响应头：
  - `Content-Type: application/octet-stream`
  - `X-Audio-Framing: wav-length-prefixed`
  - `X-Timing: {"open_ms":..., "asr_ms":..., "llm_ttft_ms":..., "tts_first_ms":...}`（open_ms = 开口延迟墙钟，唯一权威口径见 Spec §6.5）
- 客户端示例见 `measure_v02.py`（流式读取 + 帧解析 + open_ms 实测）

## 冒烟测试

```bash
venv\Scripts\python -m pytest tests/ -v    # T1~T10，T10 需模型+key+网络
```

## 说明

- ASR：sherpa-onnx + SenseVoice（本地推理，批式）；VAD：能量门限（静音拦截 → 400 no_speech）
- LLM：DeepSeek（deepseek-chat，v0.2 流式，直连不配代理），系统提示词见 Spec §7
- TTS：edge-tts 主（晓晓）/ piper 离线兜底。**edge 现网 403 → piper 实际承载**；已知宕机时短路直走 piper（不重复慢失败）；health 如实上报 active_engine/fallback_reason
- Spec：`../规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md`；自测报告：`../Code文档/v0.2自测报告.md`

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

> edge 恢复状态（OI-004）：edge-tts 6.1.12 现网持续 403（微软封老 client token），v0.2 期间 piper 实际承载，edge 保持配置主引擎；恢复评估（7.x 转码依赖 / 火山讯飞替代）为独立任务，见 Spec §6.3。
