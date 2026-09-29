#!/usr/bin/env bash
# Install Spendtrack as a launchd user agent, so it starts at login on macOS.
# Run from the project folder: scripts/install-launchd.sh
# Remove it with: scripts/install-launchd.sh --remove
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.spendtrack.plist"
LABEL="gui/$(id -u)/com.spendtrack"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $PLIST"
  exit 0
fi

PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "No virtual environment. Run 'uv sync' in $PROJECT_DIR first." >&2
  exit 1
fi

DATA_DIR="$(grep -E '^DATA_DIR=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
DATA_DIR="${DATA_DIR:-$HOME/spendtrack-data}"
DATA_DIR="${DATA_DIR/#\~/$HOME}"
mkdir -p "$DATA_DIR/logs" "$HOME/Library/LaunchAgents"

sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__DATA_DIR__|$DATA_DIR|g" \
    "$PROJECT_DIR/scripts/com.spendtrack.plist.template" > "$PLIST"

launchctl bootout "$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST. Spendtrack now starts at login."
echo "Open http://127.0.0.1:8000 in the browser."
