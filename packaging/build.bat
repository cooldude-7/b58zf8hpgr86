@echo off
REM Build TorqueTune.exe on Windows. Run from the repo root.
pip install -e . pyinstaller
pyinstaller --noconfirm packaging\tuner.spec
echo.
echo Built: dist\TorqueTune\TorqueTune.exe
