#!/usr/bin/env bash
set -euo pipefail

# Production setup helper for HM-Tradnig-Bot
# Usage:
#   sudo ./scripts/setup_prod.sh    # system-wide (recommended)
#   ./scripts/setup_prod.sh         # per-user install (no sudo)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ "$(id -u)" -eq 0 ]; then
  echo "Running as root: system-wide install (/opt/hmbot/venv)"
  VENV_DIR="/opt/hmbot/venv"
else
  echo "Running as regular user: local venv in $APP_DIR/.venv"
  VENV_DIR="$APP_DIR/.venv"
fi

echo "Creating virtualenv at $VENV_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
if [ -f "$APP_DIR/requirements.txt" ]; then
  echo "Installing Python dependencies"
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
else
  echo "No requirements.txt found in $APP_DIR"
fi

# Copy config template if missing
if [ ! -f "$APP_DIR/config/settings.json" ]; then
  echo "Creating config/settings.json from template"
  cp "$APP_DIR/config/settings.dist.json" "$APP_DIR/config/settings.json"
  echo "Please edit $APP_DIR/config/settings.json to configure MT5, dry_run, etc."
fi

# Create environment file (system-wide if root, local otherwise)
if [ "$(id -u)" -eq 0 ]; then
  ENV_TARGET="/etc/default/hmbot"
else
  ENV_TARGET="$APP_DIR/.env"
fi

if [ ! -f "$ENV_TARGET" ]; then
  cat > "$ENV_TARGET" <<EOF
# HM Bot Trader environment variables
HM_HOST=127.0.0.1
HM_PORT=8080
HM_MT5_PASSWORD=
HM_TELEGRAM_BOT_TOKEN=
HM_WEB3_API_KEY=
HM_LICENSE_KEY=
EOF
  echo "Created environment template at $ENV_TARGET"
else
  echo "Environment file already exists at $ENV_TARGET"
fi

echo "Setup complete. Next steps:" 
echo " - Edit config/settings.json and $ENV_TARGET with your secrets"
echo " - If you used root install, copy deploy/hmbot.service to /etc/systemd/system/ and enable it (see README_PRODUCTION.md)"
echo " - Optionally configure nginx as a reverse proxy using deploy/nginx_hmbot.conf"

exit 0
