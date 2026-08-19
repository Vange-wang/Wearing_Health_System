# TTS 换 CosyVoice Spec

> **⚠️ 状态：实测不可行，已回退（2026-08-19）**
> CosyVoice2-0.5B 在 RTX 3050 Laptop **4GB**（非本文所写 8G）上实测 **RTF 8.3**（合成 5.6s 音频需 46s，首包 35~46s），无法实时语音交互。已排除 load_jit/fp16 优化，瓶颈为硬件算力硬限制。Vange 拍板**回退 edge-tts**（tts_first 均值 383ms，稳定可用），云 TTS API 列为后续。
> 详见 ISSUE-0011 + `2026-08-19-CosyVoice部署承接报告_zc.md`。本 Spec 存档，未来换更强硬件可复用。

- **起草**：Hermes（deepseek-v4-pro）· 2026-08-18（2026-08-19 标记回退）
- **依据**：ISSUE-0011（选型确定 CosyVoice，Vange 拍板）+ CosyVoice2 部署/API 实测调研
- **实施**：WorkBuddy（部署 + 集成）

---

## 1. 目标

TTS 引擎从 edge-tts 换成 **CosyVoice2-0.5B（本地 3050 8G GPU）**，实现：
1. tts_first 从 edge 的 569~802ms 降到 **~150-300ms**（音色预注册后）。
2. 情感可控（CosyVoice 情感指令，补上 edge 被移除的 SSML 情感风格）。
3. 不依赖外网（本地推理，热点/断网都稳定）。

## 2. 方案

### 2.1 模型选型：CosyVoice2-0.5B

- 阿里通义开源，流式推理（合成延迟 ~150ms），音色优秀，支持零样本音色克隆。
- 显存 2-4GB（3050 8G 绰绰有余）。

### 2.2 部署环境

- conda python=3.10（CosyVoice 官方要求，py3.11+ 可能编译失败）
- 依赖：`pynini==2.1.5`（conda-forge 装）+ `requirements.txt`（aliyun mirror）
- 模型下载：`modelscope snapshot_download('iic/CosyVoice2-0.5B')`（国内魔搭，速度快）
- 环境变量：`PYTHONPATH=third_party/AcademiCodec;third_party/Matcha-TTS`

### 2.3 音色预注册（**关键，首包延迟的决定因素**）

- **坑（实测）**：零样本克隆每次推理都要编码参考音频 → 首包延迟高达 ~1.3s。
- **解法**：把「小V」音色**预注册到 spk2info**（参考音频编码结果缓存），推理时用 spk_id 直接生成，跳过参考音频编码 → 首包降到 ~150ms。
- 音色来源：首期用 CosyVoice2 预训练中文女声（或零样本克隆一个「小V」音色），注册一次，服务常驻复用。

### 2.4 集成 voice-bridge（tts.py）

- 加 `CosyVoiceEngine`（本地推理，替代 edge）。
- 接口对齐现有 TTSBase：`synthesize(text)` / `stream_synthesize(text)`（流式逐 chunk）。
- **采样率**：CosyVoice 输出 24k → 重采样 16k（帧协议不变，复用现有 miniaudio/audioop 重采样）。
- 保留 edge 作兜底（CosyVoice 加载失败/异常时切 edge，可插拔）。

### 2.5 情感控制

- CosyVoice-instruct 情感指令（`inference_instruct(text, instruct)`），配合人设「小V」。
- 首期先跑通链路 + 默认音色；情感指令调优（开心/关心/平静等）作为二期。

## 3. 关键决策（已对齐）

| # | 决策点 | 裁决 |
|---|---|---|
| 1 | 模型 | CosyVoice2-0.5B（流式 150ms） |
| 2 | 音色 | 预注册 spk2info（避免每次编码参考音频，首包 1.3s→150ms） |
| 3 | 采样率 | 24k → 16k 重采样（帧协议不变） |
| 4 | 兜底 | edge 保留（CosyVoice 异常时切回） |
| 5 | 情感 | instruct 指令，首期跑通链路，二期调优 |

## 4. 验收标准

1. CosyVoice 本地推理跑通（`synthesize` 产出 16k WAV，帧协议兼容）。
2. **tts_first ≤300ms**（音色预注册后，GPU 推理，对比 edge 569~802ms）。
3. 真机端到端对话，语音自然度优于 edge（口语化 + 情感起伏，人耳对比）。
4. CosyVoice 异常时自动兜底 edge，不崩（502 或静默降级）。
5. 显存占用 ≤4GB（3050 8G 余量充足）。

## 5. 测试要求

| ID | 用例 | 类型 |
|---|---|---|
| T1 | CosyVoice 部署 + 模型加载 + 单句合成 16k WAV | 单元 |
| T2 | 音色预注册生效（spk_id 推理，首包延迟实测） | 单元/集成 |
| T3 | tts_first 延迟实测（预注册后 ≤300ms） | 集成 |
| T4 | 真机端到端（CosyVoice 合成 + 帧播放） | 真实集成 |
| T5 | CosyVoice 异常兜底 edge | mock |
| T6 | 情感指令（instruct）合成效果 | 集成（二期） |

## 6. 风险

| 风险 | 缓解 |
|---|---|
| **音色未预注册 → 首包 1.3s** | Spec 2.3 硬要求预注册 spk2info，T2 验证 |
| Windows 部署 CosyVoice 依赖坑（pynini/编译） | conda py3.10 + conda-forge pynini，aliyun mirror；实测排障 |
| 3050 显存/算力不足 | CosyVoice2-0.5B 仅 2-4GB，8G 足够；RTF 实测 |
| 24k→16k 重采样音质损失 | miniaudio 重采样，实测听感；必要时评估帧协议升 24k（后续） |
| CosyVoice 服务常驻内存/显存 | 独立进程或懒加载 + 兜底 edge |

---

*Hermes（deepseek-v4-pro）· 2026-08-18 · 后缀 _hm 遵循 agent.md v1.5 §5.1*
