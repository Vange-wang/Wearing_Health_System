# ISSUE-0001 长期 RAG 慢路径行为级回归

## 基本信息

- Issue ID：ISSUE-0001
- 类型：regression verification（回归验证）
- 状态：open
- 优先级：P2
- 来源：`协同工作文档/审查报告/2026-08-16-长期RAG终审-确认报告.md`（长期 RAG 关闸的剩余收尾项）
- owner：WorkBuddy（开发员）
- 关联：`2026-08-15-语音桥-RAG立项-spec.md` §7 T8；v0.3 遗留 T8 行为级裁剪同源

## 描述

长期 RAG 加了轻量通道（DeepSeek + USER.md）后，需验证慢路径（完整 Hermes agent）没有被破坏：技能/工具需求仍正确走慢路径，且安抚语照发。

## 当前证据（部分，非端到端）

- T2 路由单元：三分分类（轻量/技能/工具/RAG）正确。
- v0.3 T9 安抚语测试通过（慢路径先发安抚帧）。
- 轻量通道失败（USER.md 读失败 / DeepSeek 不可达）→ 降级慢路径 Hermes，有实测日志。

## 缺失（需补的端到端一次验证）

- 真机语音触发慢路径的一次端到端验证：语音说含 `tool_keywords` 的话（如「帮我查一下快递」）→ 日志 `route=hermes`（非 lightweight）+ 第一帧安抚语「好的，我查一下。」+ 请求打到 Hermes API Server（8780）。

## 关联遗留（第二档，不阻塞本 Issue 关闭）

- 严格意义的「技能触发」（Hermes 真调 skill）依赖 `config.yaml` 的 `skill_keywords` 配置，当前为空（`[]`），技能触发词清单未从 Hermes 已装 skills 抽取。此项与 v0.3 遗留 T6 技能触发同源，可合并为独立小项，不在本 Issue 关闭条件内。

## 关闭条件

工具关键词触发慢路径的端到端验证完成并留证（日志 route=hermes + 安抚语第一帧 + 请求打 8780），Hermes 复核确认后关闭。

## 处理记录

- 2026-08-16：由 Hermes 终审登记为 open（P2，非阻断）。
