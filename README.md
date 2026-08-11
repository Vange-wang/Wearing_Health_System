# 可穿戴健康辅助系统

毕业设计项目：ESP32 传感节点（BLE）→ ESP32-S3 语音终端（WiFi）→ Hermes 智能体（DeepSeek）的语音交互健康辅助系统。

## 当前阶段

v0.1 开发准备期：硬件已下单（ESP32-S3-BOX-3 标准版，待收货）；开发环境验证 Spec 已就绪，硬件到货后由 WorkBuddy 执行；语音桥服务可独立先行开发（Spec 见 `规划文档/Spec文档/`）。

## 目录结构（学习 codex_project 格式）

    AGENTS.md            协作规则（分工/纪律/文档优先级）
    agent.md             协作流程规范（模型守卫/会话铁律/审查机制，与 AGENTS.md 冲突时以本文件为准）
    CONTEXT.md           项目背景与已敲定决策
    README.md            本文件（目录索引 + 文件放置规范）
    规划文档/
      Hermes语音开发板实现方案-20260811.docx   决策记录 + 实施计划总纲（v1.1，7 项决策已全部敲定）
      Spec文档/          功能规格（命名 YYYY-MM-DD-功能名-spec.md）
      里程碑文档/        阶段交付计划（README 说明职责）
      技术验证/          选型结论与风险记录
    Code文档/            代码结构、接口、开发记录、验证/自测报告
    协同工作文档/        交接记录、审查报告（审查报告/ 子目录）
    总负责人文档/        Hermes 决策记录
    voice-bridge/        语音桥服务源码（当前唯一代码目录）
    .workbuddy/          WorkBuddy 工作区（记忆等，不入库）

## 文件放置规范（详见 agent.md §5）

| 文件类型 | 放置位置 |
|---|---|
| 功能 Spec | `规划文档/Spec文档/YYYY-MM-DD-功能名-spec.md` |
| 选型结论/风险 | `规划文档/技术验证/YYYY-MM-DD-主题-结论.md` |
| 阶段计划 | `规划文档/里程碑文档/` |
| 验证/自测报告 | `Code文档/<阶段>-<主题>/`（如 `Code文档/v0.1-环境验证/`） |
| 审查报告 | `协同工作文档/审查报告/YYYY-MM-DD-审查-第N轮.md` |
| 交接记录 | `协同工作文档/` |
| 决策记录 | `总负责人文档/` |
| 代码 | `voice-bridge/`（venv/、models/、.env 一律不入库） |

## 分工

- Hermes：方向 / 架构 / Spec / 审核 / 验收（产出用 deepseek-v4-pro）
- WorkBuddy：按 Spec 开发代码（强制 Kimi K3，规范见 agent.md）

## 参考文档

- 毕设起草书：`D:\UserData\86166\KnownFolders\Desktop\可穿戴健康辅助系统毕设起草书.docx`
- 实现方案（项目内正本）：`规划文档/Hermes语音开发板实现方案-20260811.docx`
- 开发环境验证 Spec：`规划文档/Spec文档/2026-08-11-开发环境验证-spec-v0.1.md`
- 语音桥 Spec：`规划文档/Spec文档/2026-08-11-语音桥-spec-v0.1.md`
