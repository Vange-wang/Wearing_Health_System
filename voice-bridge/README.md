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
