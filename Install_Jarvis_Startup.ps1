$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$listener = Join-Path $root "Start_Sentinel.vbs"
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $listener -PathType Leaf)) {
    throw "Jarvis wake-listener launcher not found: $listener"
}
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "Jarvis virtual-environment Python was not found: $pythonw"
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Jarvis Wake Listener.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot "System32\wscript.exe"
$shortcut.Arguments = '"' + $listener + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Listen for the Jarvis wake word after sign-in"
$shortcut.Save()

Start-Process -FilePath $shortcut.TargetPath -ArgumentList $shortcut.Arguments -WindowStyle Hidden
Write-Host "Jarvis wake listener installed and started."
Write-Host "It will start automatically when this Windows account signs in."
