#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Remote Works Server - Installation Script
# Tested on Ubuntu 20.04
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Remote Works Server - Installation${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="remote-works-server"
VENV_DIR="$SCRIPT_DIR/venv"

# ---- 1. Check system dependencies ----
echo -e "${YELLOW}[1/6] Checking system dependencies...${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}python3 not found. Installing...${NC}"
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PYTHON_VERSION detected"

# Check for Chromium (needed for PDF generation)
CHROMIUM_PATH=""
if command -v chromium-browser &>/dev/null; then
    CHROMIUM_PATH=$(which chromium-browser)
elif command -v chromium &>/dev/null; then
    CHROMIUM_PATH=$(which chromium)
elif command -v google-chrome &>/dev/null; then
    CHROMIUM_PATH=$(which google-chrome)
elif command -v google-chrome-stable &>/dev/null; then
    CHROMIUM_PATH=$(which google-chrome-stable)
fi

if [ -z "$CHROMIUM_PATH" ]; then
    echo -e "${YELLOW}  Chromium not found. Installing chromium-browser...${NC}"
    sudo apt-get update && sudo apt-get install -y chromium-browser || {
        echo -e "${YELLOW}  chromium-browser not available, trying snap...${NC}"
        sudo snap install chromium 2>/dev/null || {
            echo -e "${RED}  WARNING: Could not install Chromium. PDF generation will not work.${NC}"
            echo -e "${RED}  Install manually: sudo apt-get install chromium-browser${NC}"
        }
    }
fi

echo -e "${GREEN}  System dependencies OK${NC}"

# ---- 2. Create virtual environment ----
echo -e "${YELLOW}[2/6] Creating Python virtual environment...${NC}"
if [ -d "$VENV_DIR" ]; then
    echo "  Virtual environment already exists, skipping"
else
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}  Virtual environment created at $VENV_DIR${NC}"
fi

# ---- 3. Install Python dependencies ----
echo -e "${YELLOW}[3/6] Installing Python dependencies...${NC}"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip > /dev/null
pip install -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}  Python dependencies installed${NC}"

# ---- 4. Install Playwright browser ----
echo -e "${YELLOW}[4/6] Installing Playwright Chromium...${NC}"
python3 -m playwright install chromium 2>/dev/null || {
    echo -e "${YELLOW}  Playwright install failed, trying with --with-deps...${NC}"
    python3 -m playwright install --with-deps chromium 2>/dev/null || {
        echo -e "${RED}  WARNING: Playwright Chromium install failed.${NC}"
        echo -e "${RED}  PDF generation will not work until fixed.${NC}"
        echo -e "${RED}  Try: sudo apt-get install -y libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 libasound2${NC}"
    }
}
echo -e "${GREEN}  Playwright setup done${NC}"

deactivate

# ---- 5. Set up password ----
echo -e "${YELLOW}[5/6] Setting up authentication...${NC}"

CONFIG_FILE="$SCRIPT_DIR/config.yaml"
source "$VENV_DIR/bin/activate"

# Generate secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f)
config['server']['secret_key'] = '$SECRET_KEY'
with open('$CONFIG_FILE', 'w') as f:
    yaml.safe_dump(config, f, default_flow_style=False)
"

echo -n "  Enter password for user '$(grep username "$CONFIG_FILE" | awk '{print $2}' | tr -d '"')': "
read -s PASSWORD </dev/tty || {
    # Fallback if stdin is not a tty
    PASSWORD=""
}
echo ""

if [ -z "$PASSWORD" ]; then
    echo -e "${RED}  WARNING: No password set. Authentication will be disabled.${NC}"
    echo -e "${RED}  Run: source venv/bin/activate && python3 -c \"from auth import get_auth; get_auth().set_password('your-password')\"${NC}"
else
    python3 -c "
from auth import get_auth
get_auth().set_password('$PASSWORD')
"
    echo -e "${GREEN}  Password set successfully${NC}"
fi

deactivate

# ---- 6. Create cache directory ----
echo -e "${YELLOW}[6/6] Setting up cache directory...${NC}"
CACHE_DIR="$HOME/.cache/remote_works_server"
mkdir -p "$CACHE_DIR/pdf"
echo -e "${GREEN}  Cache directory: $CACHE_DIR${NC}"

# ---- Summary ----
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  Project directory: $SCRIPT_DIR"
echo "  Virtual env:       $VENV_DIR"
echo "  Cache directory:   $CACHE_DIR"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit config:    nano $CONFIG_FILE"
echo "  2. Start server:   $SCRIPT_DIR/start.sh"
echo "  3. View logs:      journalctl -u $PROJECT_NAME -f"
echo ""
echo "  To install systemd service (auto-start):"
echo "    sudo cp $SCRIPT_DIR/$PROJECT_NAME.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable --now $PROJECT_NAME"
echo ""
