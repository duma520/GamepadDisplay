@echo off
cls
set PY="D:/Program Files/Python310/python.exe"
if not exist %PY% set PY=python
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q GamepadDisplay.spec 2>nul
%PY% -m PyInstaller --windowed --noconfirm --onefile --name GamepadDisplay --icon=icon.ico --add-data "icon.ico;." GamepadDisplay.py
echo.
if exist dist\GamepadDisplay.exe (echo BUILD OK: dist\GamepadDisplay.exe) else (echo BUILD FAILED)
pause
