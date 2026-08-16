# ISSUE-0008 多轮对话上下文无法联立（指代消解缺失）

## 基本信息

- Issue ID：ISSUE-0008
- 类型：feature / 上下文记忆
- 状态：**closed**
- 优先级：P2
- 来源：`2026-08-16-v0.4自测报告`（真机实测遗留）
- owner：WorkBuddy（实现）/ Hermes（复核）

## 描述

轻量通道（DeepSeek）每轮对话独立、无会话历史，导致多轮指代消解失败：「A 城市天气」→「那 B 城市呢」无法理解指代。

## 根因

`app/llm.py` 的 `chat()`/`stream_chat()` 只传单条 messages，无历史上下文。慢路径靠 persistent memory 跨轮，但轻量通道（承载绝大多数日常问题）完全无上下文。

## 修复

`LightweightLLM` 加滑动窗口会话历史（最近 4 轮 + 10 分钟过期，`HISTORY_MAX_MESSAGES` / `SESSION_TTL_SECONDS`）。验证：真实 DeepSeek「广州天气 → 那深圳呢 → 明天呢」连续三轮指代正确；新增 test_issue0008.py 3 用例，全量 29 passed。服务端已重启加载。

## 关闭记录

- 关闭时间：2026-08-16
- 关闭依据：滑动窗口会话历史 + 三轮指代消解端到端验证 + 29 passed，Hermes 复核确认。
- 备注：当前单全局会话（单 BOX-3 设备够用），未来多设备需按来源区分会话，另立评估项。

## 处理记录

- 2026-08-16：v0.4 最终自测报告登记（WorkBuddy 预登记）。
- 2026-08-16：滑动窗口会话历史实现 + 指代验证（提交 cf26f9a）。
- 2026-08-16：Hermes 复核转 closed。
