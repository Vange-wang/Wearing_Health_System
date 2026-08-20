@echo off
chcp 936 >nul 2>&1
rem ============================================================
rem  voice-bridge 自助诊断修复工具 (zcode 2026-08-20)
rem  用途：BOX-3 屏幕显示「闭嘴」或「黑脸」时，双击本文件
rem        自动诊断 + 修复，不用等开发上线。
rem ============================================================

cd /d "%~dp0"
title voice-bridge 自助诊断修复
echo ============================================
echo  voice-bridge 自助诊断修复
echo  时间: %date% %time%
echo ============================================
echo.

set ERR=0

echo [1/4] 检查 8710 端口（语音服务）...
netstat -ano | findstr ":8710" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo    OK - 8710 端口在监听
) else (
    echo    FAIL - 8710 端口没有监听，语音服务挂了
    set ERR=1
)
echo.

echo [2/4] 检查 mDNS 广播记录...
findstr /C:"广播 voicebridge" logs\mdns.log >nul 2>&1
if %errorlevel%==0 (
    echo    OK - mDNS 有过广播记录
) else (
    echo    FAIL - mDNS 无广播记录
    set ERR=1
)
echo.

echo [3/4] 检查本机能否解析 voicebridge.local...
ping -n 1 voicebridge.local >nul 2>&1
if %errorlevel%==0 (
    echo    OK - 本机能解析 voicebridge.local
) else (
    echo    FAIL - 本机解析 voicebridge.local 失败
    set ERR=1
)
echo.

echo [4/4] 检查健康接口...
curl -s http://127.0.0.1:8710/api/v1/health >nul 2>&1
if %errorlevel%==0 (
    echo    OK - 健康接口正常
) else (
    echo    FAIL - 健康接口无法访问
    set ERR=1
)
echo.

if %ERR%==0 (
    echo ============================================
    echo  全部正常，无需修复。
    echo  如果 BOX-3 屏幕仍不是笑脸：
    echo    - 检查 iPhone 热点是否开着，电脑是否连在 v2 上
    echo    - 检查 BOX-3 是否连上 WiFi
    echo ============================================
) else (
    echo ============================================
    echo  发现异常，正在自动修复...
    echo ============================================
    echo.

    echo 杀掉所有残留的 voice-bridge / mDNS 进程...
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8710" ^| findstr "LISTENING"') do (
        echo    杀 8710 进程 PID %%p
        taskkill /F /PID %%p >nul 2>&1
    )
    for /f "tokens=2 delims==" %%p in ('wmic process where "name='python.exe'" get ProcessId /value 2^>nul ^| findstr "="') do (
        wmic process where "ProcessId=%%p" get CommandLine 2>nul | findstr /C:"run.py" >nul 2>&1 && (
            echo    杀 run.py PID %%p
            taskkill /F /PID %%p >nul 2>&1
        )
        wmic process where "ProcessId=%%p" get CommandLine 2>nul | findstr /C:"mdns_advertise" >nul 2>&1 && (
            echo    杀 mdns PID %%p
            taskkill /F /PID %%p >nul 2>&1
        )
    )
    timeout /t 2 /nobreak >nul

    echo 重新启动 voice-bridge 服务 + mDNS 广播...
    if not exist logs mkdir logs
    start "" /min cmd /c "venv\Scripts\python.exe run.py >> logs\voice-bridge.log 2>&1"
    start "" /min cmd /c "venv\Scripts\python.exe mdns_advertise.py >> logs\mdns.log 2>&1"

    echo.
    echo ============================================
    echo  修复完成！等待 15 秒让服务起来...
    echo ============================================
    timeout /t 15 /nobreak >nul

    echo 复查 8710 端口...
    netstat -ano | findstr ":8710" | findstr "LISTENING" >nul 2>&1
    if %errorlevel%==0 (
        echo    OK - 8710 已恢复
    ) else (
        echo    FAIL - 8710 仍未监听，可能是环境问题
    )
)

echo.
echo ============================================
echo  下一步：
echo   1. 等 30 秒，看 BOX-3 屏幕是否变回笑脸
echo   2. 如果还是闭嘴/黑脸：
echo      - iPhone 热点开了吗？电脑连的是 v2 吗？
echo      - 重启一次 BOX-3（拔插 USB 或按 reset）
echo      - 重启电脑上的 Clash（搜索功能需要它）
echo   3. 还不行就截这个窗口发给开发
echo ============================================
echo.
pause
