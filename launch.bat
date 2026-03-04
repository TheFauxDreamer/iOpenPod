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
python -m uv --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing uv package manager...
    echo.
    call python -m pip install uv
    if errorlevel 1 goto :uv_fail
    echo.
)

REM Sync dependencies
echo Syncing dependencies...
python -m uv sync
if errorlevel 1 (
    echo.
    echo Retrying sync...
    echo.
    python -m uv sync
    if errorlevel 1 goto :sync_fail
)
echo.

echo Starting iOpenPod...
echo.
python -m uv run python main.py

echo.
echo iOpenPod has closed.
pause
exit /b 0

:uv_fail
echo.
echo [ERROR] Failed to install uv.
echo.
pause
exit /b 1

:sync_fail
echo.
echo [ERROR] Failed to sync dependencies.
echo.
pause
exit /b 1
