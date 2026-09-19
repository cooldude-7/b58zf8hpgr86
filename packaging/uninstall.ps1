<#
  Removes what install.ps1 made: shortcuts, the .tune association, the
  Apps & features entry, and the installed copy. Tune files the user saved
  live in their own documents and are never touched.

      powershell -ExecutionPolicy Bypass -File uninstall.ps1
#>
[CmdletBinding()]
param([string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\LambdaOne"))

$ErrorActionPreference = "Continue"
$AppName = "Lambda One"          # shown to a person
$AppFile = "LambdaOne"            # exe and folder names

Get-Process -Name $AppFile -ErrorAction SilentlyContinue | ForEach-Object {
    $_.CloseMainWindow() | Out-Null
    if (-not $_.WaitForExit(5000)) { $_.Kill() }
}

foreach ($dir in @((Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
                   [Environment]::GetFolderPath("Desktop"))) {
    Remove-Item (Join-Path $dir "$AppName.lnk") -Force -ErrorAction SilentlyContinue
}

# Only give .tune back if it still points at us -- another program may own it now.
$progId = "LambdaOne.Tune"
$cur = (Get-ItemProperty -Path "HKCU:\Software\Classes\.tune" -Name "(Default)" `
        -ErrorAction SilentlyContinue)."(Default)"
if ($cur -eq $progId) { Remove-Item "HKCU:\Software\Classes\.tune" -Recurse -Force -ErrorAction SilentlyContinue }
Remove-Item "HKCU:\Software\Classes\$progId" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName" `
            -Recurse -Force -ErrorAction SilentlyContinue

# The script is running from inside the directory it is deleting, so hand the
# delete to a detached shell that outlives it.
if (Test-Path $InstallDir) {
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        "-NoProfile", "-Command",
        "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$InstallDir' -Recurse -Force -ErrorAction SilentlyContinue")
}

Write-Host "$AppName removed."
