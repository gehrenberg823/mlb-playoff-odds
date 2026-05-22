#!/bin/bash
# Install/refresh the daily launchd job that runs the pipeline at 8am local time.
# Idempotent: unloads any existing copy first.
set -euo pipefail

LABEL="com.gregehrenberg.mlb-playoff-odds"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_PLIST="$PROJECT_DIR/scripts/${LABEL}.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC_PLIST" "$DEST_PLIST"

# Unload prior version if present, then load the new one
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST_PLIST"

echo "Installed launchd agent: $LABEL"
echo "Will run daily at 8:00am local time → $PROJECT_DIR/scripts/run_daily.sh"
echo
echo "Verify:    launchctl print gui/$(id -u)/${LABEL} | head -20"
echo "Run now:   launchctl kickstart gui/$(id -u)/${LABEL}"
echo "Uninstall: launchctl bootout gui/$(id -u)/${LABEL} && rm \"$DEST_PLIST\""
