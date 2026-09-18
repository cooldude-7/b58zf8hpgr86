@echo off
REM Report what is and is not installed. Reads only, changes nothing.
powershell -ExecutionPolicy Bypass -File "%~dp0doctor.ps1"
echo.
pause
