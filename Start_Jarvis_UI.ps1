param(
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"
$node = Get-Command node.exe -ErrorAction Stop
$server = Start-Process `
    -FilePath $node.Source `
    -ArgumentList "node_modules/next/dist/bin/next start -p 3000" `
    -WorkingDirectory $WorkingDirectory `
    -WindowStyle Hidden `
    -PassThru

Write-Output $server.Id
