# voice-bridge（语音桥服务 v0.1）

PC 端本地 HTTP 语音服务：接收音频 → ASR → DeepSeek → TTS → 返回音频。开发板（ESP32-S3）与大脑之间的语音通道（v0.1 暂不接 Hermes）。

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
| `GET /api/v1/health` | `{"status":"ok","asr":"ready","tts":"edge"}` |
| `POST /api/v1/voice/chat` | multipart `audio`=WAV（16k/16bit/mono ≤15s）→ 返回 WAV bytes，响应头 `X-Timing` 带各环节毫秒耗时 |

## 冒烟测试

```bash
venv\Scripts\python -m pytest tests/ -v
```

## 说明

- ASR：sherpa-onnx + SenseVoice（本地推理）；TTS：edge-tts 主（晓晓），piper 离线兜底（edge 失败自动切换，日志有 fallback 记录）
- LLM：DeepSeek（deepseek-chat，非流式，直连不配代理），系统提示词见 Spec §6
- Spec：`../规划文档/Spec文档/2026-08-11-语音桥-spec-v0.1.md`；自测报告：`../Code文档/v0.1自测报告.md`

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

> 注：edge-tts 6.1.12 现网持续 403（微软封老 client token），v0.1 实际由 piper 兜底承担 TTS。恢复 edge 见 Open-Issues OI-004（v0.2 评估）。
