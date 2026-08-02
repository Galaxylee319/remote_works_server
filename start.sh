#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    echo "Error: Virtual environment not found. Run install.sh first."
    exit 1
fi

HOST=$("$SCRIPT_DIR/venv/bin/python3" -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('host','0.0.0.0'))")
PORT=$("$SCRIPT_DIR/venv/bin/python3" -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('port',8088))")

echo "Starting Remote Works Server (v2)..."
echo "http://${HOST}:${PORT}"
echo ""

exec "$SCRIPT_DIR/venv/bin/python3" run.py

