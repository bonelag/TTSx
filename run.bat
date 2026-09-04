@echo off
cd /d "%~dp0"

if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" main.py
) else if exist "..\venv\Scripts\pythonw.exe" (
    start "" "..\venv\Scripts\pythonw.exe" main.py
) else (
    where pythonw >nul 2>&1
    if not errorlevel 1 (
        start "" pythonw main.py
    ) else (
        start "" python main.py
    )
)
exit
