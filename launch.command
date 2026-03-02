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

# Install uv if needed
if ! command -v uv &>/dev/null; then
    echo "Installing uv package manager..."
    echo
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Reload PATH so uv is available immediately
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo
        echo "[ERROR] Failed to install uv."
        echo
        read -rp "Press Enter to close..."
        exit 1
    fi
    echo
fi

# Sync dependencies
echo "Syncing dependencies..."
uv sync
if [ $? -ne 0 ]; then
    echo
    echo "[ERROR] Failed to sync dependencies."
    echo
    read -rp "Press Enter to close..."
    exit 1
fi
echo

echo "Starting iOpenPod..."
echo
uv run python3 main.py

echo
echo "iOpenPod has closed."
read -rp "Press Enter to close..."
