# CosyVoice 回退指令（给 zcode）

- **决策方**：Vange（用户）· 2026-08-19
- **执行方**：zcode（开发员）
- **背景**：`2026-08-19-CosyVoice部署承接报告_zc.md` 实测 CosyVoice2-0.5B 在 RTX 3050 Laptop 4GB 上 **RTF 8.3**（首包 35~46s），无法实时语音交互——硬件算力硬限制，非配置问题。

---

## 一、Vange 决策

**回退 edge-tts，放弃 CosyVoice 本地 TTS 路线；云 TTS API 列为后续（暂不执行）。**

## 二、zcode 执行事项

1. **确认 voice-bridge 保持 edge-tts**：不做任何 CosyVoice 集成（当前未集成，零代码改动）。系统继续跑 edge（tts_first 均值 383ms，稳定可用）。
2. **部署物归档确认**（你已列交接物，确认保留即可，不清理）：
   - 环境：`D:\miniconda\envs\cosyvoice`（py3.10，torch 2.3.1+cu121）
   - 模型：`D:\CosyVoice\pretrained_models\CosyVoice2-0.5B`（4.8GB）
   - 仓库：`D:\CosyVoice`（官方源码）
   - 验证脚本可复跑（未来换硬件复用）
3. **环境遗留问题不处理**：site-packages 损坏 dist-info（非阻塞）随环境弃用，无需清理。
4. **ISSUE-0011 已更新**（回退结论 + 云 TTS 后续候选），无需再动。

## 三、后续方向（zcode 新任务候选）

1. **BLE 健康监测**（毕设核心）：预研 `规划文档/技术验证/2026-08-17-BLE健康监测-实现路径与问题假设_hm.md`（28 问题假设 + 4 阶段路径），可立项。
2. **多 WiFi 自动切换**：Spec `规划文档/Spec文档/2026-08-18-多WiFi自动切换-spec_hm.md` 已写好，可直接实现。
3. 其余 Open Issue（0001-0012）按 ISSUE 库推进。

## 四、确认回执

zcode 确认回退完成（voice-bridge 保持 edge + 部署物归档），回报一句话即可。

---

*Hermes（deepseek-v4-pro）· 2026-08-19 · 后缀 _hm 遵循 agent.md v1.6 §5.1*
