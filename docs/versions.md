# 运行版、阶段回退和实验候选

更新于 2026-11-17。main 发布当前保留运行版源码。电脑服务来自 `64bc1b994f0a7ee1dd1e2139800acf0e25c4eb23` 的 voice-bridge，BOX3 工程来自同提交的 recovery/box3/2026-11-10-running/firmware，发布至 Code文档/固件/box3_voice_agent。原始文件内容保持一致，README 单独更新。

| 阶段 | 源码入口 | 状态 |
|---|---|---|
| 10月21日语音恢复及唤醒阈值 | [d4ba024](https://github.com/Vange-wang/Wearing_Health_System/tree/d4ba0242bd58d46d8517dec5f6a393656ba0fc0d) | 阶段留存，验收见该版本记录 |
| 10月23日BLE重连 | [f18f6b7](https://github.com/Vange-wang/Wearing_Health_System/tree/f18f6b76c7a5b6a643c6cc40485999e1f78241ef) | 阶段留存 |
| 11月8日运行回退 | [box3-running-rollback-20261108](https://github.com/Vange-wang/Wearing_Health_System/tree/box3-running-rollback-20261108) | 历史运行版 |
| 11月8日搜索时效性 | [搜索版本](https://github.com/Vange-wang/Wearing_Health_System/tree/codex/box3-search-time-20261108) | 历史源码 |
| 11月10日搜索动画 | [box3-before-search-label-20261110](https://github.com/Vange-wang/Wearing_Health_System/tree/box3-before-search-label-20261110) | 加文字之前 |
| 11月10日动画与提示文字 | [box3-before-mic-boot-20261110](https://github.com/Vange-wang/Wearing_Health_System/tree/box3-before-mic-boot-20261110) | 本次main源码基线 |
| 11月17日同步前main | [github-main-before-runtime-sync-20261117](https://github.com/Vange-wang/Wearing_Health_System/tree/github-main-before-runtime-sync-20261117) | 同步前默认分支 |

## 单独保留的候选

- [11月11日唤醒与上传恢复](https://github.com/Vange-wang/Wearing_Health_System/tree/codex/box3-wake-upload-candidate-20261111)，d63129d，未安装，仅有限真机试验准入，仍有空答语义、打断日志、实际播放与首字验证要求。
- [10月24日提示音期间收音](https://github.com/Vange-wang/Wearing_Health_System/tree/codex/box3-ack-onset-20261024)，历史候选。
- [10月24日英文字幕](https://github.com/Vange-wang/Wearing_Health_System/tree/codex/box3-english-captions-20261024)，历史候选。
- 15秒上传预算、断句和双麦模拟的其余本机实验位于 .work，未作为运行版发布。

所有既有分支和标签均保留。本次仅发布已经保留的运行源及导航；现场启动、复杂收音和长期稳定性仍待验收。设备镜像未在本次重新读取，镜像记录来自最近安装回执。
