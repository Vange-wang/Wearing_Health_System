# 仓库归一化 GitHub 发布仓统一自测报告

- 任务：T-20260831-ESP-MONOREPO-01
- 执行角色：Codex
- 日期：2026-08-31
- 当前状态：`WORKFLOW_COMPLETE`（本地同步、静态验证、主仓推送、Hermes 复审、旧仓镜像备份、旧仓删除与 404 验证均已通过）
- Spec：`规划文档/Spec文档/2026-08-31-仓库归一化主仓唯一源-spec_hm.md`
- 任务单：`协同工作文档/codex_tasks/2026-08-31-仓库归一化主仓唯一源-任务单_hm.md`

## 1. 范围

本轮只把 `D:\esp-box` 中已经通过既有冷启动伪峰锁定审查的 3 个腕带文件同步到主仓 `Code文档\固件\wrist_node`。本地 `D:\esp-box` 继续作为编译/烧录工作区；未修改 build 脚本、README、`.gitignore`、BOX-3 源码、BLE 帧、告警质量门或 voice-bridge 运行时。

## 2. 基线

- 主仓本地分支：`main`
- 主仓本地 HEAD / upstream / GitHub HEAD：`c5842f454d8c84ba4411f7330e6f2a67e86fe340`
- 主仓 origin：`https://github.com/Vange-wang/Wearing_Health_System.git`
- 旧远端 `Vange-wang/esp-box` HEAD：`4025b229e05fbd27fb4b53e287bbe3648ab0a527`
- 同步前 3 个主仓目标路径无工作树改动。
- BOX-3 关键文件 `voice_agent.c`、`build_voice.py`、`voice_agent.local.example.json` 双边 SHA-256 相同，因此按 Spec 零复制。

## 3. 同步结果

| 主仓目标文件 | 同步后 SHA-256 | 源文件 SHA-256 | 结论 |
|---|---|---|---|
| `Code文档/固件/wrist_node/main/hr_spo2.c` | `22D167519DB0BEC4C1B13694CBD407B0EFEEBAC579343DF42C1FF195FE9EA10C` | 同左 | 一致 |
| `Code文档/固件/wrist_node/main/hr_spo2_selftest.c` | `FA247BA59BCDD4D0327AD57ED9BF02EA63CCF22D8DEEC87C0D882E05807AA2DD` | 同左 | 一致 |
| `Code文档/固件/wrist_node/tests/test_wrist_algorithm_source.py` | `50AFC6575FDD45D37CBB1EE23BD1D28481827CD0667F20A018724D84BCFE80E0` | 同左 | 一致 |

`git diff --name-only -- Code文档/固件` 仅返回上述 3 个路径；`git diff --check` 无错误。Git 提示未来 checkout 可能按本机配置转换 LF/CRLF，该提示不影响当前文件 SHA 一致性，提交后仍需核对远端 blob 内容。

## 4. 静态测试

测试解释器：`voice-bridge\venv\Scripts\python.exe`

### 4.1 无效环境尝试

首次直接向 pytest 传入 `D:\esp-box\tests\...` 绝对路径但未指定 `--rootdir`，pytest 将公共父目录识别为 `D:\`，扫描系统目录 `D:\WpSystem` 后以 WinError 1337 退出，`SOURCE_EXIT=4`。该次未收集到测试，不能作为代码失败或通过证据。

### 4.2 有效源工作区验证

显式指定 `--rootdir D:\esp-box`，运行：

- `test_wrist_algorithm_source.py`
- `test_max30102_reliability_source.py`

结果：`14 passed in 0.09s`，`SOURCE_EXIT=0`。

### 4.3 有效主仓副本验证

由于该测试文件保持 D:\esp-box 的相对布局契约，本轮未修改测试源码；将主仓 `wrist_node` 文件机械复制到系统临时兼容布局后，显式指定该临时目录为 `--rootdir`，运行同一组测试。

结果：`14 passed in 0.14s`，`MAIN_ARCHIVE_EXIT=0`。临时目录在验证后经绝对路径安全检查并删除。

## 5. 边界与风险

- 未修改、删除或清理 `D:\esp-box`。
- 未导入 ESP-IDF/esp-box 上游源码、`components`、`managed_components`、build 产物、二进制、日志、缓存、真实凭据或 rollback 副本。
- 未烧录、重启或采样设备。
- 本任务是文件同步与 GitHub 操作，不进入语音运行时路径，首字输出延迟零影响。
- 当前证据已证明本地同步、静态测试、主仓远端推送、Hermes 复审、旧仓镜像备份、旧仓删除及 404 验证均已完成。

## 6. 主仓远端与 Hermes 复审

- 主仓提交：`b93a18ec4068dd2e6e3c81f6985056ada196427e`，已推送至 `Wearing_Health_System/main`。
- GitHub API 核对：远端提交恰好 5 个允许路径，3 个腕带文件解码后 SHA-256 分别为 `22D167...`、`FA247B...`、`50AFC6...`，全部匹配源；forbidden path 计数为 0。
- Hermes 审查报告：`协同工作文档/审查报告/2026-08-31-仓库归一化GitHub发布仓统一-实现与远端核验-审查_hm.md`。
- Hermes verdict：`PASS_ZERO_ISSUES`，SERIOUS=0，放行 mirror 备份门；NON_SERIOUS=1 为报告状态滞后，本次回写已处理。

## 7. 旧仓镜像备份

- mirror：`D:\repo-archive\esp-box-github-before-delete-20260831.git`
- 来源：从 GitHub `https://github.com/Vange-wang/esp-box.git` 执行 `git clone --mirror`，未依赖本地脏工作区。
- `git fsck --full`：退出码 0。
- `refs/heads/master`：`4025b229e05fbd27fb4b53e287bbe3648ab0a527`。
- 标签：`release/en_factory_demo`、`v0.1.1`、`v0.2.1`、`v0.3.0`、`v0.5.0`，missing=0、extra=0。
- 归档文件数：22；总字节数：475,826,095。
- refs 清单：`D:\repo-archive\esp-box-github-before-delete-20260831.refs.txt`，SHA-256 `2D790DED062E4C747407F5A0167019324ED3345E4118276B6582CBAA84BE89D6`。
- 文件哈希清单：`D:\repo-archive\esp-box-github-before-delete-20260831.manifest.txt`，SHA-256 `1D1DEE85EDC0B046ACE3CEBB160D0F8BAD072F574D23A286FF63860CCB446A75`。

## 8. 旧仓删除与删除后验证

- 删除前 GitHub token scopes 已包含 `delete_repo`；旧仓精确名称为 `Vange-wang/esp-box`，权限为 `ADMIN`，默认分支为 `master`，可见性为 `PUBLIC`。
- 删除前旧仓 HEAD 与镜像 `refs/heads/master` 均为 `4025b229e05fbd27fb4b53e287bbe3648ab0a527`；主仓 HEAD 为 `9be693c0ba9f41585cba746d3b9d8bcfad5f6bd5`。
- 执行 `gh repo delete Vange-wang/esp-box --yes`，退出码 0。
- 删除后 `gh repo view Vange-wang/esp-box` 退出码 1，GraphQL 返回无法解析该仓库；`gh api repos/Vange-wang/esp-box` 退出码 1，明确返回 HTTP 404。
- 删除后主仓 `Vange-wang/Wearing_Health_System` 仍可访问，权限为 `ADMIN`，默认分支为 `main`，可见性为 `PRIVATE`；删除后即时核验 HEAD 仍为 `9be693c0ba9f41585cba746d3b9d8bcfad5f6bd5`。
- 删除后本地 `D:\esp-box` 仍存在；mirror 仍存在，复跑 `git fsck --full` 退出码 0，master 为 `4025b229...`，标签数为 5。
- GitHub 旧仓已删除，不能一键恢复；如需恢复，须从本地 mirror 重新创建远端并推送 refs。

## 9. 最终结论

本任务满足 Spec 的仓库归一化边界：GitHub 发布入口统一为 `Vange-wang/Wearing_Health_System`，旧 GitHub 仓库已删除；本地编译/烧录工作区和可恢复 mirror 均保留。状态可写为 `WORKFLOW_COMPLETE`。
