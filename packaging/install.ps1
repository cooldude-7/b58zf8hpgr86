<#
  Installs TorqueTune for the current user: copies the build somewhere
  stable, then makes Start menu and desktop shortcuts, associates .tune
  files, and registers an entry in Apps & features so it uninstalls the
  way anything else does.

  Per user on purpose. A machine-wide install needs elevation, and the
  application keeps its settings and the editable shift coordinator in the
  user profile anyway.

      powershell -ExecutionPolicy Bypass -File packaging\install.ps1
      powershell -ExecutionPolicy Bypass -File packaging\install.ps1 -NoDesktop
#>
[CmdletBinding()]
param(
    [string]$Source,
    [string]$InstallDir,
    [switch]$NoDesktop
)

$ErrorActionPreference = "Stop"
$AppName = "TorqueTune"

# Work out where this script is without trusting $PSScriptRoot: in Windows
# PowerShell it comes back empty when read from a param() default, which
# fails with a Split-Path error before anything useful has happened.
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
if (-not $here) { $here = (Get-Location).Path }
$repo = Split-Path -Parent $here

if (-not $Source)     { $Source = Join-Path $repo "dist\TorqueTune" }
if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\TorqueTune" }

if (-not (Test-Path (Join-Path $Source "$AppName.exe"))) {
    throw "No build found at $Source. Run packaging\build.bat first."
}

# A running copy locks its own files, so stop it before overwriting.
Get-Process -Name $AppName -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Closing the running $AppName..."
    $_.CloseMainWindow() | Out-Null
    if (-not $_.WaitForExit(5000)) { $_.Kill() }
}

Write-Host "Installing to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
# /MIR so a rebuild that drops a file does not leave the old one behind.
# Robocopy's success codes are 0-7; anything above that is a real failure.
robocopy $Source $InstallDir /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copy failed (robocopy $LASTEXITCODE)" }
$global:LASTEXITCODE = 0

$exe = Join-Path $InstallDir "$AppName.exe"
$uninstall = Join-Path $InstallDir "uninstall.ps1"
Copy-Item (Join-Path $here "uninstall.ps1") $uninstall -Force

# Shortcuts. The icon comes from the exe itself -- the .ico is embedded at
# build time, so there is no second file to keep in step.
function New-Shortcut([string]$Path) {
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
    $sc.TargetPath = $exe
    $sc.WorkingDirectory = $InstallDir
    $sc.IconLocation = "$exe,0"
    $sc.Description = "Tuner for a torque-structured engine controller"
    $sc.Save()
}

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Shortcut (Join-Path $startMenu "$AppName.lnk")
if (-not $NoDesktop) {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk")
}

# .tune files open in the tuner. Per-user classes, so no elevation.
$progId = "TorqueTune.Tune"
New-Item -Path "HKCU:\Software\Classes\.tune" -Force | Out-Null
Set-ItemProperty -Path "HKCU:\Software\Classes\.tune" -Name "(Default)" -Value $progId
New-Item -Path "HKCU:\Software\Classes\$progId\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "HKCU:\Software\Classes\$progId" -Name "(Default)" -Value "TorqueTune tune"
Set-ItemProperty -Path "HKCU:\Software\Classes\$progId\DefaultIcon" -Name "(Default)" -Value "$exe,0"
New-Item -Path "HKCU:\Software\Classes\$progId\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "HKCU:\Software\Classes\$progId\shell\open\command" -Name "(Default)" `
                 -Value "`"$exe`" `"%1`""

# Apps & features
# Read the version from the source tree when it is there. An install run
# from an unpacked build has no source, and a missing version is not worth
# failing over.
$version = "0.0.0"
try {
    $init = Join-Path $repo "tuner\__init__.py"
    if (Test-Path $init) {
        $m = (Select-String -Path $init -Pattern 'APP_VERSION\s*=\s*"([^"]+)"').Matches
        if ($m.Count) { $version = $m[0].Groups[1].Value }
    }
} catch { }
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name DisplayName     -Value $AppName
Set-ItemProperty -Path $key -Name DisplayVersion  -Value $version
Set-ItemProperty -Path $key -Name DisplayIcon     -Value "$exe,0"
Set-ItemProperty -Path $key -Name InstallLocation -Value $InstallDir
Set-ItemProperty -Path $key -Name NoModify        -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name NoRepair        -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name UninstallString `
    -Value "powershell -ExecutionPolicy Bypass -File `"$uninstall`""

# Tell Explorer the association changed, so the new icon shows at once.
try {
    Add-Type -Namespace Shell -Name Notify -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, uint flags, IntPtr item1, IntPtr item2);
'@
    [Shell.Notify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
} catch { }

Write-Host ""
Write-Host "$AppName $version installed."
Write-Host "  Start menu and desktop shortcut created; .tune files now open in it."
Write-Host "  Right-click the taskbar icon while it runs to pin it."
Write-Host "  Remove it from Apps & features, or run $uninstall"
