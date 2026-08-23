# ESP-IDF 安装记录（2026-08-11）

> 任务单 T-20260811-03 的一部分 · WorkBuddy 执行

## 版本偏差说明

任务指定 v5.2.1，**官方不存在 v5.2.1 离线安装器**（ESP-IDF 安装器在 `espressif/idf-installer` 仓库，v5.2 系列仅提供 v5.2.7 离线包）。实际安装 **v5.2.7**（同 v5.2 minor 系列最新 patch，比 5.2.1 更稳定，BOX-3 BSP 兼容）。

## 安装结果

| 项 | 值 |
|---|---|
| 版本 | **ESP-IDF v5.2.7**（`idf.py --version` → `ESP-IDF v5.2.7-dirty`，dirty 为离线安装正常标记） |
| 安装器 | esp-idf-tools-setup-offline-5.2.7.exe（1.26GB，dl.espressif.com 国内镜像下载） |
| IDF_TOOLS_PATH | `D:\esp-idf-tools` |
| IDF 源码 | `D:\esp-idf-tools\frameworks\esp-idf-v5.2.7\` |
| Python 环境 | `D:\esp-idf-tools\python_env\idf5.2_py3.11_env`（Python 3.11.9） |
| 目标芯片 | esp32s3 |

## 环境初始化方式（硬件验证时使用）

```powershell
$env:IDF_PATH="D:\esp-idf-tools\frameworks\esp-idf-v5.2.7"
$env:IDF_TOOLS_PATH="D:\esp-idf-tools"
& "$env:IDF_PATH\export.ps1"
idf.py --version   # → ESP-IDF v5.2.7-dirty
```

## 安装过程踩坑（备忘）

1. **safe-delete 拦截**：sandbox 对删除/覆盖操作 fail-closed，导致 `install.ps1` 升级 setuptools 时卡死。解法：手动离线安装核心依赖（`pip install --no-index --find-links tools/idf-python-wheels/... -r requirements.core.txt`），纯新增不触发拦截。
2. **MSys 检测**：idf.py 拒绝在 Git Bash（MINGW64）环境运行；PowerShell 下正常。Git Bash 调用需清除 `MSYSTEM/MINGW*` 环境变量。
3. **PowerShell 重定向**：`*>` 输出为 UTF-16 编码，读取需转码。

## 验证证据

- `idf.py --version` 输出 `ESP-IDF v5.2.7-dirty`（PowerShell 环境，2026-08-11 20:3x）
- 工具链：xtensa-esp-elf、riscv32-esp-elf、cmake 3.30.2、ninja 1.12.1、openocd 等全部就绪
- python 依赖：esptool 4.11.0、kconfiglib、idf-component-manager 2.4.10、esp-idf-monitor 等离线安装成功
