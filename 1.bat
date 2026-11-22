@echo off
cls
set PY="D:/Program Files/Python310/python.exe"
if not exist %PY% set PY=python
%PY% GamepadDisplay.py
pause
