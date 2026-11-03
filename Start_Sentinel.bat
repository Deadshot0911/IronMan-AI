@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Jarvis virtual environment not found.
    echo Run: python -m venv .venv
    echo Then install the project dependencies into .venv before starting the wake listener.
    exit /b 1
)
start "" /b "%~dp0.venv\Scripts\pythonw.exe" "%~dp0sentinel.py"
exit