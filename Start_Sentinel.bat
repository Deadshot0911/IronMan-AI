@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Jarvis virtual environment not found.
    echo Run: python -m venv .venv
    echo Then install the project dependencies into .venv before starting Sentinel.
    pause
    exit /b 1
)
start "" /min "%~dp0.venv\Scripts\python.exe" "%~dp0sentinel.py"
exit