# 仓库归一化 GitHub 发布仓统一完成报告

- 任务：T-20260831-ESP-MONOREPO-01
- 执行角色：Codex
- 日期：2026-08-31
- 当前状态：`WORKFLOW_ACTIVE`
- 当前结论：本地 3 文件同步和静态自测通过；完整任务未完成，仍待主仓推送、远端核验、Hermes 复审、旧仓镜像备份与删除。

## 已完成

1. 冻结主仓、`D:\esp-box` 与两个 GitHub 仓库基线；确认主仓本地/上游/远端均为 `c5842f454d8c84ba4411f7330e6f2a67e86fe340`。
2. 确认 BOX-3 关键源码与主仓哈希一致，按 Spec 不重复复制。
3. 仅同步腕带 `hr_spo2.c`、`hr_spo2_selftest.c`、`test_wrist_algorithm_source.py`，目标 SHA-256 分别为 `22D167...`、`FA247B...`、`50AFC6...`，均与源一致。
4. 源工作区静态测试 `14 passed`；主仓副本临时兼容布局静态测试 `14 passed`。
5. 固件差异集合仅上述 3 个文件；未触碰本地构建路径、BOX-3、voice-bridge、BLE 8 字节帧、告警门或首字路径。

## 未完成门禁

1. 显式暂存、提交并推送 `Wearing_Health_System/main`。
2. 核对 GitHub 远端 commit 和 3 个文件内容，确认无 secret/build artifact。
3. 取得既有 Hermes session 的独立迁移复审通过结论。
4. 从 GitHub 对 `Vange-wang/esp-box` 执行完整 `clone --mirror` 备份，验证 `fsck`、`master` 和 5 个 tags。
5. 获取 `delete_repo` scope，二次核对 owner/name，删除旧仓并验证 404。

## 删除安全边界

- 旧仓删除前，主仓远端验证、Hermes 复审和镜像备份必须全部通过；任一失败即停止。
- 旧仓为 public、主仓为 private，删除后公共访问消失。
- 本地 `D:\esp-box` 永不删除，继续作为编译/烧录工作区。
- 删除后的远端恢复依赖本地 mirror 重新创建并 push，不能声称一键恢复。

## 唯一下一动作

复核 staged 精确路径后提交并推送主仓；本报告不把准备或局部门禁通过写成 `WORKFLOW_COMPLETE`。
