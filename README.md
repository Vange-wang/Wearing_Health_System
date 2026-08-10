# 可穿戴健康辅助系统

毕业设计项目：ESP32 传感节点（BLE）→ ESP32-S3 语音终端（WiFi）→ Hermes 智能体（DeepSeek）的语音交互健康辅助系统。

## 当前阶段

v0.1：PC 端语音桥服务开发（Spec 见 `规划文档/Spec文档/`）。硬件尚未购买，语音桥可独立先行开发与测试。

## 目录结构（学习 codex_project 格式）

    AGENTS.md            协作规则（分工/纪律/文档优先级）
    CONTEXT.md           项目背景与已敲定决策
    README.md            本文件
    规划文档/
      Spec文档/          功能规格（语音桥 spec 等）
      里程碑文档/        阶段交付计划
      技术验证/          选型结论、风险
    Code文档/            代码结构、接口、开发记录
    协同工作文档/        验收与沟通记录
    总负责人文档/        Hermes 决策记录
    voice-bridge/        语音桥服务源码（当前唯一代码目录）

## 分工

- Hermes：方向 / 架构 / Spec / 审核 / 验收
- WorkBuddy：按 Spec 开发代码

## 参考文档

- 毕设起草书：`D:\UserData\86166\KnownFolders\Desktop\可穿戴健康辅助系统毕设起草书.docx`
- 实现方案：`D:\UserData\86166\KnownFolders\Desktop\Hermes语音开发板实现方案-20260811.docx`
