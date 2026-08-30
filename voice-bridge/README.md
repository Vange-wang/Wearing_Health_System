# voice-bridge（语音桥服务 · 长期 RAG）

PC 端本地 HTTP 语音服务：**Hermes 的语音前端 + 轻量通道三层路由**——接收音频 → VAD → ASR → 路由 → 分句 TTS → 长度前缀帧流返回。

## 三层路由（长期 RAG，Spec A2）

```
用户语音 → ASR → 路由判定（app/router.py）
        ├ 纯闲聊/简单问答 → 轻量通道（DeepSeek 裸模型 + USER.md 注入）→ ~1.5s
        ├ 知识库查询 → BM25 检索 + DeepSeek 裸模型 → ~1.5s
        └ 需技能/复杂工具 → 完整 Hermes agent（先安抚「我查一下」）→ ~3.5s
```

- **共用记忆**：轻量通道只读 `~/.hermes/memories/USER.md`（不读 MEMORY.md），与微信共享同一份；慢路径走 Hermes agent 自然共享。
- **轻量失败兜底**：DeepSeek 不可达 / USER.md 读失败 → 自动降级慢路径 Hermes，不崩。
- **知识库**：`knowledge/*.md` 每条一个文件；BM25 + jieba 检索；`POST /api/v1/knowledge/reload` 热重载。

## Hermes 侧准备（v0.3 起）

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
  sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/   # ASR：SenseVoice（批式）
  sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/ # ASR：zipformer（流式，v0.4）

# 4. Hermes API Server key、DeepSeek key 与设备令牌（不入库）：复制到 .env
#    HERMES_API_KEY=<与 Hermes 侧 API_SERVER_KEY 相同>
#    DEEPSEEK_API_KEY=<轻量通道用，DeepSeek 直连>
#    DEVICE_TOKEN=<与 BOX-3 NVS 中相同的设备令牌>
#    DEVICE_AUTH_MODE=required
```

## 部署检查（上线前必查）

- **环境不得有代理变量**（AGENTS.md 红线）：`HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 必须为空。
  - 原因：edge-tts 库内部 `trust_env=True`，若服务进程环境存在代理变量，edge 合成流量会走代理，延迟特征改变甚至失败。
  - 检查（Windows PowerShell）：
    ```powershell
    $env:HTTP_PROXY; $env:HTTPS_PROXY; $env:ALL_PROXY   # 三者均应为空（无输出）
    ```
  - voice-bridge 自身对 DeepSeek/edge 直连已用 `trust_env=False`，但 edge-tts 库内部不受控，故须从环境层面杜绝代理变量。

## 启动

```bash
venv\Scripts\python run.py      # 监听 0.0.0.0:8710
```

## 接口

| 接口 | 说明 |
|---|---|
| `GET /api/v1/health` | `{"status":"ok","asr":"ready","tts":{...},"vad":"enabled","llm":"hermes"}` |
| `POST /api/v1/health/data` | BOX-3 上报经质量门处理的心率/血氧数据 |
| `GET /api/v1/health/alert` | BOX-3 空闲轮询告警；无告警返回 204，有告警返回带 `X-Alert-ID` 的 WAV 帧流 |
| `POST /api/v1/health/alert/{id}/ack` | BOX-3 完整播放后确认告警；重复确认幂等 |
| `POST /api/v1/voice/chat` | （v0.1 保留，非流式）multipart `audio`=WAV → 完整 WAV bytes + `X-Timing` |
| `POST /api/v1/voice/chat/stream` | （流式）multipart `audio`=WAV → 长度前缀帧流（三层路由） |
| `POST /api/v1/voice/stream` | BOX-3 生产路径：16kHz/16bit/mono 原始 PCM 分块上传 → 长度前缀 WAV 帧流 |
| `POST /api/v1/knowledge/reload` | 热重载知识库（重新扫描 `knowledge/*.md`）→ `{"status":"ok","count":N}` |

除公开健康检查和知识库维护接口外，设备路径必须携带 `X-Device-Token`。最终配置固定为 `required`：缺失令牌返回 401，错误令牌返回 403；`observe` 只允许用于受控升级窗口，不得作为最终交付状态。

## 流式帧协议（v0.2 起不变）

- 每帧 = `[4 字节大端 uint32 长度 N]` + `[N 字节 = 一句完整 WAV（16kHz/16bit/mono）]`；EOF = 响应体结束；8MB 帧长守卫
- 响应头：`Content-Type: application/octet-stream` + `X-Audio-Framing: wav-length-prefixed` + `X-Timing`

## 重构后的模块边界（2026-08-30）

- `app/device_auth.py`：设备令牌校验与 `observe`/`required` 受控切换。
- `app/audio_input.py`：原始 PCM/WAV 的大小、时长、帧对齐和 5 秒流空闲超时；停滞请求返回 408 并释放独占会话锁。
- `app/alert_outbox.py`：告警 `pending → leased → acknowledged` 持久化状态机，失败或服务重启后可重投。
- `app/health.py`：心率/血氧分字段新鲜度、flags/quality 质量门与连续异常判定。
- `app/pipeline.py`：请求级状态、首帧即下发和性能打点；不把完整回复生成放到首字前。
- `app/wechat_alert.py`：仅发送成功后计入每日额度；失败按退避策略重试，不绕过平台限额。

## 分段计量（v0.3 新增，Spec §4）

`X-Timing` 含：`open_ms` / `asr_ms` / `llm_ttft_ms` / `tts_first_ms` / **`tool_ms`（工具期，如实上报不卡线）** / **`answer_open_ms`（答案期 = open_ms - tool_ms，验收卡 ≤1600ms）** / `llm_backend`。纯闲聊 tool_ms=0。

## 冒烟测试

```bash
venv\Scripts\python -m pytest tests/ -v        # v0.2 回归 + v0.3 套件
# v0.3 真实集成（T4~T6/T8）：需 HERMES_E2E=1 + HERMES_API_KEY + API Server 运行
```

## 说明

- ASR：sherpa-onnx + SenseVoice（批式）+ **zipformer 流式**（v0.4 A2，真机 `/voice/stream` 用）；VAD：能量门限（静音拦截 → 400 no_speech）
- LLM：**Hermes API Server**（慢路径）+ **DeepSeek 轻量通道**（纯闲聊/知识库，注入 USER.md）；三层路由（技能/工具→Hermes，知识库→RAG，其余→轻量）
- TTS：**edge-tts 7.2.8 唯一**（v0.4 A5 弃 piper）：合成 24k mp3 → miniaudio 解码重采样 16k → WAV；edge 故障报 502（不兜底）；句间 300ms 停顿 + 小数点消歧（A6）
- Spec：`../规划文档/Spec文档/2026-08-16-语音桥-spec-v0.4.md`；自测报告：`../Code文档/自测报告/v0.4自测报告.md`
