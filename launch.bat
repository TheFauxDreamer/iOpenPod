@echo off
title iOpenPod
cd /d "%~dp0"

echo ==========================================
echo   iOpenPod Launcher
echo ==========================================
echo.

REM Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Download Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Show Python version
echo Found:
python --version
echo.

REM Install dependencies if needed
python -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo Installing dependencies (first run only, this may take a minute)...
    echo.
    python -m pip install PyQt6 numpy Pillow pycryptodome mutagen pyusb dearpygui
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo Try running manually: python -m pip install PyQt6 numpy Pillow pycryptodome mutagen pyusb dearpygui
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed successfully.
    echo.
)

echo Starting iOpenPod...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] iOpenPod exited with an error.
    echo.
    pause
    exit /b 1
)

pause
