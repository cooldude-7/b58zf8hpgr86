@echo off
REM Install an already-built TorqueTune for the current user.
REM Double-click this, or run it from anywhere. Use build.bat instead if
REM dist\TorqueTune does not exist yet.
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 goto :failed
echo.
echo Done. Look for TorqueTune on the desktop and in the Start menu.
goto :end

:failed
echo.
echo INSTALL FAILED -- the error is above this line.

:end
echo.
pause
