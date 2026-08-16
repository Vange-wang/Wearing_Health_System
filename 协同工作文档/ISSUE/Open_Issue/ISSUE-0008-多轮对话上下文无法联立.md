# ISSUE-0008 多轮对话上下文无法联立（指代消解缺失）

## 基本信息

- Issue ID：ISSUE-0008
- 类型：feature / 上下文记忆
- 状态：open
- 优先级：P2
- 来源：`2026-08-16-v0.4自测报告`（真机实测遗留，WorkBuddy 预登记，待 Hermes 确认）
- owner：WorkBuddy（实现）/ Hermes（方案审批）

## 描述

轻量通道（DeepSeek）**每轮对话独立、无会话历史**，导致多轮指代消解失败。真机实测典型样例：

- 问「A 城市天气怎么样」→ 收到回答后问「那 B 城市呢」→ 模型无法理解「B 城市呢」是在追问天气，答非所问或不知所指。

## 根因（已定位）

- `app/llm.py` 的 `chat()` / `stream_chat()` 只传单条 `messages=[{"role": "user", "content": user_text}]`，**无 history 参数、不携带历史上下文**。
- 慢路径（Hermes）靠 persistent memory 实现跨轮记忆，但轻量通道（DeepSeek，承载绝大多数日常问题）**完全没有上下文**。

## 关闭条件

1. 轻量通道接入短期会话历史（如最近 N 轮 / 滑动上下文窗口），不改变「慢路径靠 persistent memory」的既有架构。
2. 指代消解端到端验证：连续两轮追问（如「A 城市天气」→「B 城市呢」）能正确理解指代并作答。
3. Hermes 复核确认后关闭。

## 处理记录

- 2026-08-16：v0.4 最终自测报告登记（WorkBuddy 预登记），待 Hermes 确认。
