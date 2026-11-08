@echo off
chcp 936 >nul 2>&1
rem 安全重试兼容入口；不按端口、进程名或子串终止任何服务。
call "%~dp0start-voice-bridge.bat"
exit /b %errorlevel%
