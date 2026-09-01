# ISSUE-0013 跨路径上下文联动断裂（"重新说一遍"丢上下文）

## 基本信息

- Issue ID：ISSUE-0013
- 类型：bug（多轮对话体验）
- 状态：**closed**
- 优先级：P1
- 来源：真机复现（2026-08-21 01:27:15→01:27:33）+ 任务单 `zcode_tasks/2026-08-21-跨路径上下文联动-任务单_hm.md`
- owner：zcode（实现）/ Hermes（审查）
- 登记人：Hermes（2026-08-21）

## 描述

真机复现：

```
01:27:15 「我的生日是什么时候」→ route=hermes（慢路径）→ 小V 答出生日
01:27:33 「重新说一遍」      → route=lightweight ❌ → 小V 不知道要干什么
```

**根因（两处叠加）**：

1. **路由误判**：`重新说一遍` 含"说"字 → 命中 `NEW_TOPIC_SIGNALS`（新话题信号）→ 判为新话题 → 不延续上一轮。但"重新说一遍"是明确追问（指代上一轮回答）——`FOLLOWUP_HINTS` 缺词（重新/再说/重复/刚才/一遍）且新话题信号误伤；
2. **跨路径历史断裂**：`LightweightLLM._history`（deque）只记 lightweight 轮次（`_remember` 只在 llm.py:326/368 调用）；上一轮 hermes 慢路径对话不进 deque → 即便路由对了，轻量通道也没有上一轮上下文。

**影响**：慢路径（搜索/记忆查询）之后的指代追问（重新说一遍/再说一遍/刚才那个）全部失效，多轮对话体验断裂。

## 修复方向（任务单已定）

1. 路由：`FOLLOWUP_HINTS` 补"重新/再说/重复/刚才/一遍"等词，追问词优先级高于新话题信号；
2. 历史：HermesLLM 加 `remember_round`，pipeline 在慢路径回复完成后写共享 deque（方案 A）；不行则 deque 提升到 pipeline 层（方案 B）；
3. 验收：生日→重新说一遍→再答出生日；搜索→重新说一遍→复述结果；回归 62 passed。

## 关闭条件

- 真机「我的生日是什么时候」→「重新说一遍」→ 再次答出生日（不丢上下文）；
- 慢路径搜索后指代追问不答非所问；
- 全量单测通过 + 新增路由用例（"重新说一遍"= followup）。

## 关闭记录

- 关闭时间：2026-09-01
- 关闭依据（四条全部满足，证据可复读）：
  1. 实现完成：router.py（`classify_followup` + REPLAY/CONTEXT 复合短语）/ pipeline.py（单轮 600s TTL 快照 + REPLAY 重播 + CONTEXT 四路闭合），Hermes R3 独立审查 PASS（SERIOUS 0 / NON_SERIOUS 0，OI-1/OI-2/OI-3 全 CLOSED）；
  2. 自动化自测：全量 `pytest tests -q` = 195 passed / 5 skipped / 1 warning（Hermes 关闭裁决时独立重跑一致），相对基线新增 23 测试、0 fail；
  3. BOX-3 真机行为：生日（route=rag）→「重新说一遍」（route=replay，llm_backend=replay，零二次 LLM、无安抚语）复述相同生日；天气（route=hermes）→「刚才那个呢」（route=context）延续天气回答、不答非所问（原始日志 `验收与澄清/2026-09-01-ISSUE-0013-BOX3真机验收原始数据_cdx/`）；
  4. 设备侧首字主门：固定口令「你好」有效 N=10 中位数 1391.754ms < 冻结红线 1484.589ms，余量 92.835ms，普通路径无回退（P95 2037.571ms 如实保留为长尾记录）。
- 最终裁决：Hermes session `20260901_155843_9f8136`，报告 `审查报告/2026-09-01-ISSUE-0013-BOX3真机验收与关闭裁决_hm.md`。

## 处理记录

- 2026-08-21：真机复现登记（Hermes），任务单 `zcode_tasks/2026-08-21-跨路径上下文联动-任务单_hm.md`。
- 2026-09-01：实现 + 自测（Codex，_cdx）；Hermes R1/R2/R3 三轮审查（R3 PASS）。
- 2026-09-01：BOX-3 真机语音与首字验收（Codex/Vange，_cdx）。
- 2026-09-01：Hermes 最终关闭裁决，转 closed（session `20260901_155843_9f8136`）。
