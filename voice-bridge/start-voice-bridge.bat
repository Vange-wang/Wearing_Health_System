@echo off
rem voice-bridge 启动脚本（服务端 + mDNS 广播）
rem 自启入口：启动文件夹 voice-bridge-autostart.bat 调用本脚本
cd /d "%~dp0"
if not exist logs mkdir logs
start "" /min cmd /c "venv\Scripts\python.exe run.py >> logs\voice-bridge.log 2>&1"
start "" /min cmd /c "venv\Scripts\python.exe mdns_advertise.py >> logs\mdns.log 2>&1"
exit /b 0
