#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
else
    echo "Error: Virtual environment not found. Run install.sh first."
    exit 1
fi

# Read config for host:port
HOST=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['server']['host'])")
PORT=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['server']['port'])")

echo "Starting Remote Works Server..."
echo "http://${HOST}:${PORT}"
echo ""

exec python3 server.py
