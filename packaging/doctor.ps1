<#
  Reports the state of a TorqueTune install in one pass: what was built,
  what was installed, what shortcuts and registry entries exist, and
  whether the art is where the app looks for it. Reads only -- it changes
  nothing.

      powershell -ExecutionPolicy Bypass -File packaging\doctor.ps1
#>
$ErrorActionPreference = "Continue"
$AppName = "TorqueTune"

$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Definition }
if (-not $here) { $here = (Get-Location).Path }
$repo = Split-Path -Parent $here

function Say($label, $ok, $detail) {
    $mark = if ($ok) { "yes" } else { "NO " }
    Write-Host ("  [{0}] {1,-34} {2}" -f $mark, $label, $detail)
}

Write-Host ""
Write-Host "TorqueTune doctor"
Write-Host "  repo: $repo"

Write-Host ""
Write-Host "Checkout"
try {
    Push-Location $repo
    $branch = (git rev-parse --abbrev-ref HEAD 2>$null)
    $commit = (git log -1 --format="%h %s" 2>$null)
    Pop-Location
    Say "branch" ($branch -eq "claude/zen-goldberg-jdw51o") $branch
    Write-Host ("       commit                             {0}" -f $commit)
} catch { Say "git" $false "not available" }

Write-Host ""
Write-Host "Build  ($repo\dist\TorqueTune)"
$built = Join-Path $repo "dist\$AppName\$AppName.exe"
Say "exe built" (Test-Path $built) $built
$srcAssets = Join-Path $repo "dist\$AppName\_internal\tuner\ui\assets"
foreach ($f in @("torquetune.ico", "icon.png", "splash.png")) {
    Say "  $f" (Test-Path (Join-Path $srcAssets $f)) ""
}

Write-Host ""
$dir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
Write-Host "Install  ($dir)"
$exe = Join-Path $dir "$AppName.exe"
Say "installed exe" (Test-Path $exe) ""
foreach ($f in @("torquetune.ico", "icon.png", "splash.png")) {
    Say "  $f" (Test-Path (Join-Path $dir "_internal\tuner\ui\assets\$f")) ""
}

Write-Host ""
Write-Host "Shortcuts"
# Both of these can be empty on an odd profile; a diagnostic must report
# that rather than throw its own error over the top of the answer.
$links = @{}
if ($env:APPDATA) {
    $links["Start menu"] = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"
}
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop -and $env:USERPROFILE) { $desktop = Join-Path $env:USERPROFILE "Desktop" }
if ($desktop) { $links["Desktop"] = Join-Path $desktop "$AppName.lnk" }

foreach ($name in @("Start menu", "Desktop")) {
    if (-not $links.ContainsKey($name)) {
        Say $name $false "(no such folder on this profile)"
        continue
    }
    $lnk = $links[$name]
    $ok = Test-Path $lnk
    $detail = $lnk
    if ($ok) {
        try {
            $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
            $detail = "-> $($sc.TargetPath)  icon: $($sc.IconLocation)"
        } catch { $detail = "(unreadable)" }
    }
    Say $name $ok $detail
}

Write-Host ""
Write-Host "Registry"
$progId = (Get-ItemProperty "HKCU:\Software\Classes\.tune" -Name "(Default)" -ErrorAction SilentlyContinue)."(Default)"
Say ".tune association" ($progId -eq "TorqueTune.Tune") $progId
$cmd = (Get-ItemProperty "HKCU:\Software\Classes\TorqueTune.Tune\shell\open\command" -Name "(Default)" -ErrorAction SilentlyContinue)."(Default)"
Say "open command" ([bool]$cmd) $cmd
$unin = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName" -ErrorAction SilentlyContinue
Say "Apps & features entry" ([bool]$unin) $(if ($unin) { "$($unin.DisplayName) $($unin.DisplayVersion)" })

Write-Host ""
Write-Host "Icon embedded in the exe"
foreach ($cand in @($exe, $built)) {
    if (Test-Path $cand) {
        try {
            Add-Type -AssemblyName System.Drawing
            $ic = [System.Drawing.Icon]::ExtractAssociatedIcon($cand)
            Say (Split-Path -Leaf $cand) ($null -ne $ic) "$($ic.Width)x$($ic.Height) from $cand"
        } catch { Say (Split-Path -Leaf $cand) $false $_.Exception.Message }
    }
}

Write-Host ""
Write-Host "Paste everything above."
Write-Host ""
