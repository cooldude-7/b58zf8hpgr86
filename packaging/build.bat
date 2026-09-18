@echo off
REM Build TorqueTune.exe on Windows and install it for the current user.
REM Run from the repo root.  build.bat /nodesktop  skips the desktop icon.
REM
REM No multi-line ( ) blocks in this file on purpose: if it ever reaches a
REM machine with LF line endings, cmd mis-parses those and silently skips
REM the rest of the script, which looks exactly like the build succeeding
REM and nothing else happening.

pip install -e . pyinstaller
if errorlevel 1 goto :buildfailed

pyinstaller --noconfirm packaging\tuner.spec
if errorlevel 1 goto :buildfailed

echo.
echo Built: dist\TorqueTune\TorqueTune.exe
echo.
echo Installing...

if /i "%~1"=="/nodesktop" goto :nodesktop
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 goto :installfailed
goto :done

:nodesktop
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1" -NoDesktop
if errorlevel 1 goto :installfailed
goto :done

:buildfailed
echo.
echo BUILD FAILED -- nothing was installed. The error is above this line.
goto :end

:installfailed
echo.
echo INSTALL FAILED -- the exe is built and runnable at
echo   dist\TorqueTune\TorqueTune.exe
echo but no shortcut was made. The error is above this line.
goto :end

:done
echo.
echo Done. Look for TorqueTune on the desktop and in the Start menu.

:end
echo.
pause
