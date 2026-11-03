@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Jarvis virtual environment not found.
    echo Run: python -m venv .venv
    echo Then install the project dependencies into .venv before starting Jarvis.
    exit /b 1
)

if not exist "jarvis-ui\node_modules\next\dist\bin\next" (
    echo Jarvis UI dependencies are missing. Run npm install in jarvis-ui.
    exit /b 1
)

powershell.exe -NoProfile -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', 3000); exit 0 } catch { exit 1 } finally { $client.Dispose() }"
if errorlevel 1 (
    if not exist "jarvis-ui\.next\BUILD_ID" (
        echo Building the Jarvis UI for first launch...
        pushd "jarvis-ui"
        call npm run build
        if errorlevel 1 (
            popd
            echo Jarvis UI build failed.
            exit /b 1
        )
    ) else (
        pushd "jarvis-ui"
    )
    start "" /b cmd /c "npm run start -- -p 3000"
    powershell.exe -NoProfile -Command "for ($i = 0; $i -lt 90; $i++) { $client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', 3000); $client.Dispose(); exit 0 } catch { $client.Dispose(); Start-Sleep -Seconds 1 } }; exit 1"
    if errorlevel 1 (
        popd
        echo Jarvis UI did not start on port 3000.
        exit /b 1
    )
    popd
)

".venv\Scripts\python.exe" jarvis_core.py
