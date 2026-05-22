#!/bin/bash
# Install a daily 8am ET cron entry to run the pipeline.
# Idempotent: re-running replaces only this project's entry.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$PROJECT_DIR/scripts/run_daily.sh"
TAG="# playoff_odds_ev"

chmod +x "$RUNNER"

# 8am ET → set TZ in the cron line so it doesn't depend on system tz
NEW_ENTRY="0 8 * * * TZ=America/New_York $RUNNER $TAG"

# Strip any prior entry for this project, then append the new one
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$TAG" > "$TMP" || true
echo "$NEW_ENTRY" >> "$TMP"
crontab "$TMP"
rm "$TMP"

echo "Installed cron entry:"
crontab -l | grep "$TAG"
