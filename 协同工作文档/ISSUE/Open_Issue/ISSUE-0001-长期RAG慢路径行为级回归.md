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

慢路径端到端验证完成并留证：① 日志 route=hermes + 请求打 8780；② 安抚语触发条件改为 **route=hermes**（覆盖慢路径全量，不依赖 tool_seen），第一帧安抚语留证。Hermes 复核确认后关闭。

## 处理记录

- 2026-08-16：由 Hermes 终审登记为 open（P2，非阻断）。
- 2026-08-16（离线端到端验证，edge 合成语音走 /api/v1/voice/stream 同接口）：「帮我查一下快递」「帮我查一下天气」两句均 **route=hermes（tool keyword: 帮我查）+ llm_backend=hermes + 请求打 8780** 已留证（日志 stream_done）。但 `comfort_sent=false`（tool_seen=false）——Hermes 对这两句未发起工具调用，故安抚语第一帧未触发。**待办**：确认 Hermes 侧工具调用是否生效（或换能触发 Hermes 工具的话复测），补齐「安抚语第一帧」留证后转 Hermes 复核。
- 2026-08-16（真机复测「帮我查一下快递」）：**route=hermes + 打 8780 已留证**（`llm_backend=hermes`）；但 `comfort_sent=false`（tool_seen=false，Hermes 未调工具）+ **慢路径极慢：llm_ttft 22.3s、open_ms 24.4s**——Hermes agent 思考 22s 才首 token，且无安抚语兜底，用户体感「无回复」（干等 24s）。**新增发现：安抚语当前只在 Hermes 调工具时触发，但慢路径的慢是「agent 思考」本身，不调工具同样慢——安抚语应覆盖「慢路径全量」，而非仅「工具哨兵」**。此项需与 Hermes 对齐（安抚语触发条件 + 慢路径延迟优化）。
