# ISSUE-0003 技能触发词清单抽取与技能触发验证

## 基本信息

- Issue ID：ISSUE-0003
- 类型：feature / configuration（功能配置缺口）
- 状态：open
- 优先级：P2
- 来源：v0.3 遗留 T6 技能触发未测；长期 RAG Spec §3「技能触发词清单由 WorkBuddy 从 Hermes 已装 skills 抽取维护」
- owner：WorkBuddy（开发员）
- 关联：`voice-bridge/config.yaml` `router.skill_keywords`（当前为空 `[]`）；ISSUE-0001（慢路径回归第二档同源）

## 描述

长期 RAG 三层路由里，慢路径（完整 Hermes agent）的触发依赖两类关键词：`tool_keywords`（工具需求，已配）和 `skill_keywords`（技能触发词，**未配**）。`skill_keywords` 当前为空，导致「语音触发已装 skill 走慢路径、Hermes 真调 skill」的场景无法验证。

## 待办

1. 从 Hermes 已装 skills 抽取触发词（如成分决策 → 「看成分/这个面霜/化妆品成分」等）。
2. 配置进 `config.yaml` 的 `router.skill_keywords`。
3. 验证：语音说含技能触发词的话 → `route=hermes` → Hermes 调 skill 返回结果。

## 关闭条件

skill_keywords 配置完成 + 语音触发技能走慢路径的端到端验证通过（Hermes 真调 skill），Hermes 复核确认后关闭。

## 处理记录

- 2026-08-16：由 Hermes 登记为 open（P3，v0.3 T6 与长期 RAG 慢路径回归第二档的延续）。
- 2026-08-16：Hermes 对齐升级 **P2**——实时查询编造问题（系统对「查天气」编造）暴露 skill_keywords 空 + 工具调用未生效的严重性，技能触发（含 Hermes tool-calling 打通）是正解路径（见 `2026-08-16-实时查询能力缺口-对齐回复.md`）。
