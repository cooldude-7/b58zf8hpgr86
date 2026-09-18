@echo off
REM Build TorqueTune.exe on Windows and install it for the current user.
REM Run from the repo root.  build.bat /nodesktop  skips the desktop icon.
pip install -e . pyinstaller
pyinstaller --noconfirm packaging\tuner.spec
if errorlevel 1 goto :eof
echo.
echo Built: dist\TorqueTune\TorqueTune.exe
echo.
if /i "%~1"=="/nodesktop" (
    powershell -ExecutionPolicy Bypass -File packaging\install.ps1 -NoDesktop
) else (
    powershell -ExecutionPolicy Bypass -File packaging\install.ps1
)
if errorlevel 1 (
    echo.
    echo INSTALL FAILED -- the exe is built and runnable at
    echo   dist\TorqueTune\TorqueTune.exe
    echo but no shortcut was made. The error is above this line.
)
echo.
pause
