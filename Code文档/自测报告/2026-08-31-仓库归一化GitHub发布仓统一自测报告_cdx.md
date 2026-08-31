# 仓库归一化 GitHub 发布仓统一自测报告

- 任务：T-20260831-ESP-MONOREPO-01
- 执行角色：Codex
- 日期：2026-08-31
- 当前状态：`WORKFLOW_ACTIVE`（本地同步与静态验证通过；远端推送、Hermes 复审、镜像备份和旧仓删除尚未完成）
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
- 当前证据仅证明本地同步和静态测试；不能声称已推送、Hermes 已复审、镜像已备份或旧 GitHub 仓已删除。

## 6. 下一门

使用显式路径暂存 3 个腕带文件及本报告/完成报告，复核 staged 集合与 secret/artifact 边界后提交并推送 `Wearing_Health_System/main`。
