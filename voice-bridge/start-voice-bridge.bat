@echo off
setlocal
title Checking voice service
echo Checking voice service
set "PY=%~dp0venv\Scripts\python.exe"
set "PYW=%~dp0venv\Scripts\pythonw.exe"
if not exist "%PY%" goto missing
if not exist "%PYW%" goto missing
rem The GUI entry provides persistent native feedback if Tk cannot load/create.
rem Avoid a separate interpreter/Tk import before showing the real status window.
"%PYW%" "%~dp0service_control_window.py" %*
if errorlevel 1 goto failed
exit /b 0
:missing
chcp 65001 >nul 2>&1
echo Cannot start voice service: Python interpreter is missing.
echo Python path: "%PY%"
echo Pythonw path: "%PYW%"
echo Check README.md in the project voice-bridge directory.
pause
exit /b 2
:failed
chcp 65001 >nul 2>&1
echo Tk/GUI dependency or control entry failed to initialize. Check README.md and the service logs.
echo Pythonw path: "%PYW%"
echo Entry path: "%~dp0service_control_window.py"
pause
exit /b 4
