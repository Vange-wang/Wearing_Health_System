# ISSUE-0006 opus 广域网压缩优化

## 基本信息

- Issue ID：ISSUE-0006
- 类型：future optimization（未来优化）
- 状态：open
- 优先级：P3
- 来源：`2026-08-16-v0.4-A1A2查证-裁决报告.md`（A1 裁决 opus 改 raw PCM，opus 登记 future）
- owner：WorkBuddy（评估）/ Hermes（审批依赖）

## 描述

v0.4 局域网场景采用 raw PCM（16k/16bit/mono = 32KB/s，局域网带宽可忽略），零编解码依赖。若未来支持**广域网远程访问**（BOX-3 不在 PC 同一局域网），32KB/s 的 PCM 上传会占带宽、加延迟，需 opus 压缩（16~24kbps，约 16 倍压缩）。

## 已知阻碍（v0.4 查证实测）

- 服务端 Windows 上「纯 pip 解裸 opus 包」无干净方案：opencore 编译挂、pyogg 仅 OGG 容器、opuslib 需系统 libopus DLL。
- 固件侧 esp-opus 1.0.5 已 M0 V-09 验证可编码，编码侧无阻碍，阻碍在服务端解码。

## 关闭条件

广域网场景评估启动时，解决服务端 opus 解码依赖（捆绑 libopus DLL / 改用 OGG 容器 / 其他方案），并验证 opus 压缩在广域网下的收益，Hermes 审批后关闭。

## 处理记录

- 2026-08-16：由 Hermes 裁决登记为 open（P3，future optimization，v0.4 局域网用 raw PCM 不阻塞）。
