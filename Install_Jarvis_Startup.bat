@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Jarvis virtual environment was not found. Create it before installing startup.
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install_Jarvis_Startup.ps1"
if errorlevel 1 (
    echo Could not install the Jarvis startup listener.
    exit /b 1
)
