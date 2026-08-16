# ISSUE 总表

更新日期：2026-08-16

维护：Hermes（审查方）登记，WorkBuddy（开发员）执行，Vange 拍板。

来源说明：本表记录可穿戴健康辅助系统项目的 Issue 编号、状态、优先级、责任方与关闭条件。Issue 编号稳定，不随状态变化复用或改号。状态流转：`open → closed`（满足关闭条件 + 证据可复读）或 `open → withdrawn`（明确不处理）。

## Open Issue

| id | title | type | status | priority | owner | 关闭条件摘要 |
| --- | --- | --- | --- | --- | --- | --- |
| `ISSUE-0001` | 长期 RAG 慢路径行为级回归 | regression verification | open | P2 | WorkBuddy | 工具关键词触发慢路径 + 安抚语第一帧（已改 route=hermes 触发，留证复核） |
| `ISSUE-0002` | BM25 无语义检索语义增强 | future improvement | open | P3 | WorkBuddy / Hermes | 语义增强方案（bge-onnx 等）立项评估后采纳或否决 |
| `ISSUE-0003` | 技能触发词清单抽取与技能触发验证 | feature / configuration | open | P2 | WorkBuddy | 抽取 skill 触发词配置 skill_keywords + 语音触发技能走慢路径端到端验证 |
| `ISSUE-0004` | 唤醒词（预制词 → 自定义训练） | future feature | open | P3 | WorkBuddy | 预制词唤醒实现 + 自定义唤醒词训练走通 |
| `ISSUE-0005` | 电池供电（USB → 锂电） | future hardware | open | P3 | 待定 | 锂电供电实现 + 续航验证 |
| `ISSUE-0006` | opus 广域网压缩优化 | future optimization | open | P3 | WorkBuddy / Hermes | 解决服务端 opus 解码依赖 + 验证广域网压缩收益 |
| `ISSUE-0009` | 流式 ASR 真人发音准确率基线 | accuracy baseline | open | P3 | WorkBuddy | 真人发音采样评估，记录准确率基线 |
| `ISSUE-0010` | 会话级路由记忆（指代追问延续慢路径） | feature / routing | open | P2 | WorkBuddy / Hermes | 上轮慢路径→本轮指代追问延续慢路径 + 端到端验证真查 |

## Closed Issue

| id | title | type | status | priority | 关闭依据 |
| --- | --- | --- | --- | --- | --- |
| `ISSUE-0007` | 流式 ASR 个别字词识别不够清晰 | accuracy | closed | P2 | 尾静音截断根因 + 15/15 标准发音（真人发音转 ISSUE-0009） |
| `ISSUE-0008` | 多轮对话上下文无法联立 | feature | closed | P2 | 滑动窗口会话历史 + 三轮指代消解验证 |

## Withdrawn Issue

（暂无）

## 关闭统一条件

Issue 仅在以下条件满足后允许关闭：

- 上表「关闭条件摘要」满足，且有可复读的证据（日志 / 截图 / 提交 / 报告）。
- Hermes 复核确认，或 Vange 验收确认。

关闭后文件移至 `Close_Issue/`，总表状态更新为 `closed`；明确不处理的移至 `Withdrawn_Issue/`，状态 `withdrawn`。

---

*历史遗留（OI-001~007）已全关闭，见 `协同工作文档/审查报告/Open-Issues.md`；本库 ISSUE-XXXX 系列为后续遗留管理。*
