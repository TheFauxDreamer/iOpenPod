@echo off
REM Double-click this file to launch iOpenPod on Windows.
cd /d "%~dp0"

python -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo Installing dependencies (first run only)...
    python -m pip install --quiet PyQt6 numpy Pillow pycryptodome mutagen pyusb dearpygui
)

python main.py
pause
