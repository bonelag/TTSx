@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title TTSx Studio - Setup Environment

cd /d "%~dp0"

echo ====================================================================
echo  TTSx Studio - Khoi tao & Cai dat moi truong tu dong
echo ====================================================================
echo.

:: Kiem tra Python tren he thong
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Khong tim thay Python tren he thong!
        echo Vui long cai dat Python 3.9 - 3.12 va tich chon "Add Python to PATH".
        echo Download tai: https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
) else (
    set PYTHON_CMD=python
)

:: Chay script setup.py va truyen toan bo tham so (%*)
%PYTHON_CMD% setup.py %*

if errorlevel 1 (
    echo.
    echo [ERROR] Co loi xay ra trong qua trinh cai dat.
    echo.
    pause
    exit /b 1
)

echo.
pause
