#!/bin/bash
# Launch iOpenPod on Linux.
# Make executable: chmod +x launch.sh
# Then run: ./launch.sh
cd "$(dirname "$0")"

# Install dependencies if needed (only runs pip on first launch)
if ! python3 -c "import PyQt6" 2>/dev/null; then
    echo "Installing dependencies (first run only)..."
    python3 -m pip install --quiet -r <(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    deps = tomllib.load(f)['project']['dependencies']
for d in deps:
    print(d)
")
fi

python3 main.py
