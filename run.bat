@echo off
title TTSx Studio (Portable)
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" main.py
) else if exist "..\venv\Scripts\python.exe" (
    "..\venv\Scripts\python.exe" main.py
) else (
    python main.py
)
if errorlevel 1 (
    echo.
    echo [!] Da xay ra loi khi khoi chay ung dung.
    pause
)
