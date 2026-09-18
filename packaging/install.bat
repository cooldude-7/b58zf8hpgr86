@echo off
REM Install an already-built TorqueTune for the current user.
REM Double-click this, or run it from the repo root. Use build.bat instead
REM if dist\TorqueTune does not exist yet.
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -File "packaging\install.ps1" %*
echo.
pause
