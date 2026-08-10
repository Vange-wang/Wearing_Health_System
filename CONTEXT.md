# CONTEXT.md — 项目上下文

## 一句话

毕业设计：基于人体区域无线传感网络与大语言模型的便携式智能健康辅助系统——传感节点采集生理数据，AI 终端语音交互 + 大模型健康分析。

## 架构（已敲定）

    可穿戴节点(ESP32: 腕部心率/血氧/运动, 胸部ECG…)
        │ BLE
        ▼
    便携式AI终端 = ESP32-S3 语音板（同时是 BLE 中心节点 + WiFi 语音端）
        │ WiFi（2.4G，支持手机热点）
        ▼
    电脑/云端：Hermes 智能体（大脑：记忆/技能/会话） + 语音桥服务（ASR/TTS）
        │ DeepSeek API（直连，不配代理）
        ▼
    回答生成

## 已敲定决策（2026-08-11）

1. 总体路线：Hermes 自搭建，不用现成小智方案（记忆共用 + 微信联动 + agent 能力）
2. 开发板 = 语音通道（接入端），不部署 Hermes 本体
3. 硬件：ESP32-S3 语音板（BLE 为标配），倾向带屏 BOX-3（满足毕设"数据显示"）
4. 三通道共用同一大脑/记忆：语音板、微信(iLink)、电脑终端
5. 延迟目标：开口延迟 1~1.5s（全流式），完整回复播完 3~5s 正常
6. 部署路径：阶段1 电脑端验证 → 全绿后阶段2 腾讯云轻量服务器（profile 整体迁移）
7. 语音引擎（已敲定）：
   - ASR：sherpa-onnx + SenseVoice 中文模型（本地，近实时）
   - TTS：Edge-TTS 晓晓（zh-CN-XiaoxiaoNeural）优先，piper 离线兜底
   - 全部可插拔，后续可换火山/讯飞云 API
8. 分工：Hermes = 大脑/方向/Spec/审核；WorkBuddy = 代码开发
9. 关联文档：毕设起草书《可穿戴健康辅助系统毕设起草书.docx》（真实桌面）、桌面《Hermes语音开发板实现方案-20260811.docx》

## 关键事实

- 真实桌面 = D:\UserData\86166\KnownFolders\Desktop（C 盘桌面为重定向，放文件用 D 盘路径）
- Python：3.12 被 PEP668 锁（externally-managed），python-docx 等包在 Python 3.11 user site，生成 docx 用 `C:\Users\86166\AppData\Local\Programs\Python\Python311\python.exe`
- ESP32 仅支持 2.4G WiFi；手机热点需开 2.4G/最大兼容性模式
- DeepSeek 直连已优化（首字节 <1s）
