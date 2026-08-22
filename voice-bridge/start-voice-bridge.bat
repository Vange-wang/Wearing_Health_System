@echo off
rem voice-bridge 全栈启动（voice-bridge + mDNS + memory_server）
rem 用途：手动启动 / Windows 计划任务自启 / 唤醒恢复
rem 不会重复启动：已监听端口的服务会被跳过

setlocal enabledelayedexpansion

cd /d "%~dp0"
if not exist logs mkdir logs

rem --- 检查函数：端口已被监听则跳过 ---
rem voice-bridge (8710)
netstat -ano 2>nul | findstr ":8710" | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] 启动 voice-bridge... >> logs\autostart.log
    start "" /min cmd /c "venv\Scripts\python.exe run.py >> logs\voice-bridge.log 2>&1"
) else (
    echo [%date% %time%] voice-bridge 已在运行，跳过 >> logs\autostart.log
)

rem mDNS
tasklist 2>nul | findstr /i "mdns_advertise" >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] 启动 mDNS... >> logs\autostart.log
    start "" /min cmd /c "venv\Scripts\python.exe mdns_advertise.py >> logs\mdns.log 2>&1"
) else (
    echo [%date% %time%] mDNS 已在运行，跳过 >> logs\autostart.log
)

rem memory_server (8781)
netstat -ano 2>nul | findstr ":8781" | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] 启动 memory_server... >> logs\autostart.log
    set "HERMES_HOME=C:\Users\86166\.hermes"
    start "" /min cmd /c "D:\miniconda\python.exe C:\Users\86166\.hermes\scripts\memory_server.py >> C:\Users\86166\.hermes\logs\memory_server.log 2>&1"
) else (
    echo [%date% %time%] memory_server 已在运行，跳过 >> logs\autostart.log
)

rem 等待启动完成
timeout /t 5 /nobreak >nul
echo [%date% %time%] 全栈启动完成 >> logs\autostart.log
exit /b 0
