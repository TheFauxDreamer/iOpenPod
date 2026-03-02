@echo off
title iOpenPod
cd /d "%~dp0"

echo ==========================================
echo   iOpenPod Launcher
echo ==========================================
echo.

REM Check Python is installed
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Download Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo Found:
python --version
echo.

REM Install uv if needed
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing uv package manager...
    echo.
    python -m pip install uv
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Failed to install uv.
        echo.
        pause
        exit /b 1
    )
    echo.
)

REM Sync dependencies
echo Syncing dependencies...
uv sync
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to sync dependencies.
    echo.
    pause
    exit /b 1
)
echo.

echo Starting iOpenPod...
echo.
uv run python main.py

echo.
echo iOpenPod has closed.
pause
