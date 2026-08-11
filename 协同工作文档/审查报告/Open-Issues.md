# Open Issues — voice-bridge 项目遗留项跟踪

> 本文件登记审查中有条件通过的 NON_SERIOUS 遗留项。每次任务交接时随附未关闭清单，确保不丢失。
> 关闭条件：责任方完成修复/决策 + 对方确认。

| 编号 | 描述 | 严重度 | 状态 | 责任方 | 登记日期 | 关闭日期 |
|---|---|---|---|---|---|---|
| OI-001 | health tts 字段只返回主引擎名（如 "edge"），edge 不可用时仍显示 "edge"，未反映实际可用引擎。建议 v0.2 改进为显示实际可用引擎（如 "piper(fallback)"）或连通性检查 | NON_SERIOUS | open | WorkBuddy | 2026-08-11 | — |
| OI-002 | Spec §8 ASR 模型资产名 `sherpa-onnx-sense-voice-zh-20240418` 不存在，需修正为 `sense-voice-zh-en-ja-ko-yue-int8-2024-07-17` | NON_SERIOUS | open | Hermes | 2026-08-11 | — |
| OI-003 | main.py:80 TTS 未就绪时的 error detail 硬编码 "TTS 未就绪"，不像 ASR/LLM 用启动时捕获的具体错误信息（asr_load_error/llm_config_error）。建议统一 | NON_SERIOUS | **closed** | WorkBuddy | 2026-08-11 | 2026-08-11 |
| OI-004 | edge-tts 主引擎不可用（微软封 6.x token, HTTP 403），v0.1 实际 piper 独撑 TTS。v0.2 需评估恢复方案：升 edge-tts 7.x+音频转码（需引入 ffmpeg/pydub，评估是否违反依赖红线）或替换为火山/讯飞云 TTS | NON_SERIOUS | open | Hermes | 2026-08-11 | — |
| OI-005 | piper-tts 1.6.0 Windows espeak-ng-data 打包 bug（编译机硬编码路径），当前通过目录联接（junction）修复。迁移机器/重装 venv 时需重建 junction，建议 README 补操作步骤 | NON_SERIOUS | **closed** | WorkBuddy | 2026-08-11 | 2026-08-11 |
| OI-006 | edge-tts venv vendor patch（communicate.py outputFormat 改为 riff-16khz-16bit-mono-pcm），重装 edge-tts 会覆盖。建议 README 补充 patch 恢复步骤或在 requirements-dev.txt 中加自动化脚本 | NON_SERIOUS | **closed** | WorkBuddy | 2026-08-11 | 2026-08-11 |
| OI-007 | SenseVoice 对纯静音/低能量音频会幻觉出噪声字符（如韩文字符），当前通过 0 帧 WAV 触发 no_speech 兜底。v0.2 建议加 VAD 或能量门限做前置过滤 | NON_SERIOUS | open | Hermes | 2026-08-11 | — |

---

*最后更新：2026-08-11 · 审查轮次：第1轮/共3轮 · 关联报告：2026-08-11-审查-第1轮.md*
