# 腕部冷启动完整真机矩阵原始数据归档

- 生成日期：2026-08-31
- 产出方：Codex
- 源会话 JSONL：$sessionPath
- 源会话 SHA-256：$sessionHash
- 提取规则：仅选择 cwd=D:/esp-box、stdout 含行首 CAPTURE_PORT=COM6/COM7 的 CommandExecution 记录。
- 捕获清单：8 轮有效采样 + 1 段未复位作废采样；作废数据保留但 alid_for_matrix=false。
- 外部参照：Vange 明确确认此前及之后回传值均按稳定读数中位口径。
- 矩阵首轮开始（北京时间）：2026-08-31 17:52:06.178 +08:00
- 矩阵末轮结束（北京时间）：2026-08-31 18:30:00.250 +08:00
- 矩阵墙钟跨度：2274.072 秒（包含换手、放置和确认间隔）
- 采集命令累计执行：942.095 秒

## 文件

- aw_serial_captures_cdx.json：9 次命令的完整原始 stdout、执行 ID、JSONL 行号、复位方式和外部参照。
- aw_serial_captures_cdx.log：便于人工阅读的完整原始串口输出，不删减 DIAG、FRAME、SUMMARY 或复位证据。
- rames_cdx.csv：逐帧 HR、SpO2、confidence、flags、seq 与派生有效性字段。
- signal_diag_cdx.csv：逐窗口 rate、DC/AC、band、quality、flags。
- capture_summary_cdx.csv：每轮脚本原始 SUMMARY 与外部参照。
- xternal_reference_cdx.csv：Vange 每轮外部血氧仪原话和规范化中位数。
- xtract_wrist_matrix_evidence_cdx.ps1：可复现提取脚本。
- vidence_manifest_cdx.json：归档文件大小与 SHA-256。

## 数量校验

- 原始捕获：9
- 有效捕获：8
- 作废捕获：1
- 有效捕获全部帧：170
- 作废捕获帧：9
- 有效稳定段帧：103
- 干净 HR 帧：52
- 有效 SpO2 帧：39
- 稳定段 98--114 bpm 且 HR bit0 有效：0
- 稳定段 SpO2<90 且 bit1 有效：0

此目录保留原始数据和派生数据。矩阵验收结论见同日 _cdx 真机矩阵报告；原始数据不因后续审查或算法调整而删除或覆盖。
