@echo off
rem One-shot full-stack recovery through the verified watchdog checks.
rem The watchdog uses exact PID/CIM command-line ownership for mDNS.

setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" exit /b 2

"venv\Scripts\python.exe" "voice-bridge-watchdog.pyw" --check-once
exit /b %errorlevel%
