# CosyVoice 部署承接报告（zcode 接手 WB 下载任务）

- **承接方**：zcode（智谱 GLM）· 2026-08-19
- **任务**：承接 WB 未完成的 CosyVoice 部署下载任务（Spec `2026-08-18-TTS换CosyVoice-spec_hm.md`）
- **结论先行**：**依赖已全部打通、模型加载成功、合成链路跑通；但实测 RTF 8.3（合成 5.6s 音频需 46s，首包 35~46s），在当前硬件（RTX 3050 Laptop 4GB）上无法实时，Spec 目标 tts_first ≤300ms 不可达。建议回退 edge-tts，或换更强硬件/更小模型。**

---

## 一、承接时现场状态（WB 遗留）

| 项 | 状态 |
|---|---|
| 仓库 / conda py3.10 环境 | ✅ 已就绪 |
| 依赖安装 | 🔄 卡死：2 个 pip 进程 CLOSE_WAIT（挂死在对 Clash 代理 127.0.0.1:7800 的连接） |
| 模型下载 | ❌ 未开始 |
| 集成 voice-bridge | ❌ 未开始 |

## 二、我做的工作（按顺序）

1. **清理 WB 僵死进程**：`26720`/`29476` 两个 pip 进程卡在 CLOSE_WAIT（WB 用 `--proxy 127.0.0.1:7800` 装依赖被代理断连挂死），已终止。
2. **修版本冲突 + 逐层补损坏模块**（WB 的 site-packages 已被反复折腾污染，逐项修复）：
   - `huggingface_hub 1.27→0.36.2`、`tokenizers 0.23rc→0.21.4`（对齐 transformers 4.51.3）
   - `mpmath`（重装 1.3.0，修 circular import）
   - `openai-whisper`（需 `setuptools<81` 恢复 pkg_resources + `--no-build-isolation`）
   - `conformer`/`diffusers`/`librosa`/`matplotlib` 均为**损坏空目录/残包**（WB 的 download_deps.py 解包污染），全部重装
   - `numpy 2.2.6→1.26.4`（onnxruntime 1.18 崩溃 `_ARRAY_API not found`）
   - 补 `torchmetrics`/`wget`
3. **下载模型**：CosyVoice2-0.5B 完整下载（4.8GB，含 llm.pt 2GB、speech_tokenizer_v2.onnx 473MB、CosyVoice-BlankEN 988MB 等）。
4. **加载 + 合成验证**（见下）。

## 三、部署验证结果

| 验证项 | 结果 | 判定 |
|---|---|---|
| AutoModel import | IMPORT_OK | ✅ |
| 模型加载 | 55.4s，采样率 24000 | ✅ |
| 显存占用 | 2.4GB（fp32 参数常驻） | ✅ 4GB 装得下 |
| 音色预注册 `add_zero_shot_spk` | True，1054ms | ✅ |
| 单句合成 | 5.6s 音频正常产出（24kHz） | ✅ 功能通 |
| **首包延迟（预注册后）** | **35~46 秒** | ❌ **不可实时** |
| **RTF** | **8.3**（比实时慢 8 倍，load_jit 无改善 8.34） | ❌ |

## 四、关键发现（修正 Spec / 澄清事实）

1. **pynini 根本不需要**：Spec §2.2 写「pynini==2.1.5」，但实测 CosyVoice 代码和 `wetext==0.0.4` **均无 pynini 引用**（wetext 0.0.4 用 `kaldifst` 做 FST）。WB 卡在 pynini 是白绕弯路。我已装 pynini（conda-forge win-64 有），但属多余，无害。
2. **显卡是 4GB 不是 8GB**：Spec 写「3050 8G」，实际是 **RTX 3050 Laptop，显存 4.0GB**。这是 Spec 需要修正的硬事实。
3. **fp16 语义澄清**：CosyVoice 的 `fp16=True` 是推理时 `torch.cuda.amp.autocast`（动态混合精度），**不是 `half()`**——模型参数保持 fp32，显存没减半（2.4GB）。

## 五、RTF 8.3 根因（为何不能实时）

| 因素 | 说明 |
|---|---|
| 3050 Laptop 算力弱 | 2048 CUDA 核心、入门级，0.5B LLM 自回归生成是主瓶颈 |
| 显存 4GB 偏紧 | fp32 模型 2.4GB + 激活峰值 3.4GB，逼近上限 |
| flash attention 缺失 | torch 2.3.1 未编译 FA，回退 SDPA 慢 |
| load_jit 无效 | 实测 RTF 8.34，无改善（瓶颈在 LLM 自回归，非 Python 开销） |

**判定**：CosyVoice2-0.5B 在 3050 Laptop 4GB 上 RTF ~8.3，完全不能支撑流式语音交互（一句话要等 40+ 秒）。这不是配置/依赖问题，是**硬件算力的硬限制**。

## 六、建议（供 Vange / Hermes 决策）

| 方案 | 可行性 | 说明 |
|---|---|---|
| **回退 edge-tts（推荐）** | ✅ | 当前已优化（tts_first 均值 383ms、首字 open_ms 均值 1.56s），稳定可用；放弃本地 TTS |
| 换更强硬件 | 视条件 | 桌面 3060 12G / 4060 及以上，RTF 才可能 <1；需 Vange 决策成本 |
| 换更小模型 | 存疑 | CosyVoice-300M（0.3B）估计 RTF 仍 ~4-5，大概率仍不实时；可实测但预期不乐观 |
| 云 TTS API（火山/讯飞） | ✅ 但违背「本地」决策 | 国内 RTT 低、音色好，但引入外网依赖 + 成本 |

**建议**：暂停 CosyVoice 本地 TTS 路线，回退 edge-tts（ISSUE-0011 暂挂），把精力转向 BLE 健康监测（毕设核心）与多 WiFi 切换。

## 七、交接物（后续如需继续本地 TTS）

- 环境：`D:\miniconda\envs\cosyvoice`（py3.10，torch 2.3.1+cu121，依赖已通）
- 模型：`D:\CosyVoice\pretrained_models\CosyVoice2-0.5B`（4.8GB 完整）
- 仓库：`D:\CosyVoice`（CosyVoice 官方源码）
- 验证脚本：本报告第三节的加载/合成命令可直接复跑

## 附：环境遗留问题（非阻塞）

- site-packages 仍有 4 个损坏 dist-info 目录（`-kl`/`-ntlr4-python3-runtime`/`-uggingface-hub`/`-umpy`），pip 每次报「Ignoring invalid distribution」警告但**不影响 import**。彻底清理需重建 env，暂不处理。

*zcode（智谱 GLM）· 2026-08-19 · 承接 WB 部署任务产出，后缀 _zc 遵循 agent.md v1.5 §5.1*
