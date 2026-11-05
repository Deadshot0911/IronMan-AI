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

$legacyTask = Get-ScheduledTask -TaskName "Jarvis Sentinel" -TaskPath "\" -ErrorAction SilentlyContinue
if ($legacyTask) {
    $legacyAction = @($legacyTask.Actions) | Where-Object {
        $_.Execute -and
        [IO.Path]::GetFullPath($_.Execute) -ieq [IO.Path]::GetFullPath($pythonw) -and
        $_.Arguments.Trim('"') -ieq "sentinel.py" -and
        $_.WorkingDirectory -and
        [IO.Path]::GetFullPath($_.WorkingDirectory) -ieq [IO.Path]::GetFullPath($root)
    }

    if ($legacyAction) {
        $removeTask = @"
`$ErrorActionPreference = "Stop"
Stop-ScheduledTask -TaskName "Jarvis Sentinel" -TaskPath "\" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Jarvis Sentinel" -TaskPath "\" -Confirm:`$false -ErrorAction Stop
"@
        $encodedCommand = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes($removeTask)
        )
        $elevatedPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $cleanup = Start-Process -FilePath $elevatedPowerShell -Verb RunAs -Wait -PassThru `
            -ArgumentList @("-NoProfile", "-EncodedCommand", $encodedCommand)

        if ($cleanup.ExitCode -ne 0 -or
            (Get-ScheduledTask -TaskName "Jarvis Sentinel" -TaskPath "\" -ErrorAction SilentlyContinue)) {
            throw "Could not remove the legacy non-interactive Jarvis Sentinel task. Approve the administrator prompt and run this installer again."
        }

        Write-Host "Removed the legacy non-interactive Jarvis Sentinel task."
    }
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
