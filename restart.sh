#!/usr/bin/env bash
# Restart the Spendtrack launchd agent after a code update.
# Run from any folder: ./restart.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="gui/$(id -u)/com.spendtrack"

if ! launchctl print "$LABEL" >/dev/null 2>&1; then
  echo "The agent is not installed. Run scripts/install-launchd.sh first." >&2
  exit 1
fi

cd "$PROJECT_DIR"
uv sync
launchctl kickstart -k "$LABEL"
echo "Restarted $LABEL."
