# 仓库归一化 GitHub 发布仓统一完成报告

- 任务：T-20260831-ESP-MONOREPO-01
- 执行角色：Codex
- 日期：2026-08-31
- 当前状态：`WORKFLOW_COMPLETE`
- 当前结论：本地同步、主仓推送、远端核验、Hermes 复审、旧仓镜像备份、旧仓删除与 404 验证均已通过；GitHub 发布仓已统一为 `Vange-wang/Wearing_Health_System`。

## 已完成

1. 冻结主仓、`D:\esp-box` 与两个 GitHub 仓库基线；确认主仓本地/上游/远端均为 `c5842f454d8c84ba4411f7330e6f2a67e86fe340`。
2. 确认 BOX-3 关键源码与主仓哈希一致，按 Spec 不重复复制。
3. 仅同步腕带 `hr_spo2.c`、`hr_spo2_selftest.c`、`test_wrist_algorithm_source.py`，目标 SHA-256 分别为 `22D167...`、`FA247B...`、`50AFC6...`，均与源一致。
4. 源工作区静态测试 `14 passed`；主仓副本临时兼容布局静态测试 `14 passed`。
5. 固件差异集合仅上述 3 个文件；未触碰本地构建路径、BOX-3、voice-bridge、BLE 8 字节帧、告警门或首字路径。
6. 提交 `b93a18ec4068dd2e6e3c81f6985056ada196427e` 已推送到 `Wearing_Health_System/main`；远端提交仅 5 个允许路径，3 个目标文件 SHA-256 全部匹配。
7. Hermes 独立复审 verdict=`PASS_ZERO_ISSUES`，SERIOUS=0，已放行 mirror 备份门。
8. 旧仓 GitHub mirror 已保存到 `D:\repo-archive\esp-box-github-before-delete-20260831.git`；`fsck=0`，master 与 5 个 tags 齐全。refs 清单 SHA-256=`2D790D...`，文件清单 SHA-256=`1D1DEE...`。
9. GitHub token 已取得 `delete_repo` scope；删除前再次确认旧仓为 `Vange-wang/esp-box`、权限 `ADMIN`、HEAD=`4025b229...`，且主仓、本地源码、mirror 与清单哈希全部匹配。
10. `gh repo delete Vange-wang/esp-box --yes` 退出码 0；删除后 GraphQL 无法解析仓库，REST 明确返回 HTTP 404。主仓仍可访问且即时 HEAD=`9be693c...`，本地 `D:\esp-box` 仍存在，mirror 复跑 `fsck=0`、master 与 5 个 tags 保持完整。

## 门禁结论

无未完成门禁。旧仓删除、404 验证、主仓存续验证、本地工作区存续验证及 mirror 完整性复验均通过。

## 删除安全边界

- 旧仓删除前，主仓远端验证、Hermes 复审和镜像备份必须全部通过；任一失败即停止。
- 旧仓为 public、主仓为 private，删除后公共访问消失。
- 本地 `D:\esp-box` 永不删除，继续作为编译/烧录工作区。
- 删除后的远端恢复依赖本地 mirror 重新创建并 push，不能声称一键恢复。

## 恢复说明

GitHub 旧仓已永久删除，不能一键恢复；如未来确需恢复，可基于 `D:\repo-archive\esp-box-github-before-delete-20260831.git` 重新创建远端并推送全部 refs。本地 `D:\esp-box` 未删除，继续作为实际编译/烧录工作区。

## 最终状态

本任务已满足确认 Spec 与任务单，状态为 `WORKFLOW_COMPLETE`。后续腕带真机完整验收矩阵属于原算法任务的独立后补项，不影响本次 GitHub 仓库归一化闭环。
