#!/bin/bash
# Double-click this file to launch iOpenPod on macOS.
cd "$(dirname "$0")"

echo "=========================================="
echo "  iOpenPod Launcher"
echo "=========================================="
echo

# Check Python is installed
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo
    echo "Install it from https://www.python.org/downloads/"
    echo "or via Homebrew: brew install python"
    echo
    read -rp "Press Enter to close..."
    exit 1
fi

echo "Found: $(python3 --version)"
echo

# Install dependencies if needed
if ! python3 -c "import PyQt6" 2>/dev/null; then
    echo "Installing dependencies (first run only, this may take a minute)..."
    echo
    python3 -m pip install -r <(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    deps = tomllib.load(f)['project']['dependencies']
for d in deps:
    print(d)
")
    if [ $? -ne 0 ]; then
        echo
        echo "[ERROR] Failed to install dependencies."
        echo "Try running manually: python3 -m pip install PyQt6 numpy Pillow pycryptodome mutagen pyusb dearpygui"
        echo
        read -rp "Press Enter to close..."
        exit 1
    fi
    echo
    echo "Dependencies installed successfully."
    echo
fi

echo "Starting iOpenPod..."
python3 main.py &
disown
