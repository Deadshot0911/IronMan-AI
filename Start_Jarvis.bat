@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Jarvis virtual environment not found.
    echo Run: python -m venv .venv
    echo Then install the project dependencies into .venv before starting Jarvis.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" jarvis_core.py
exit