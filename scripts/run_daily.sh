#!/bin/bash
# Wrapper for the daily cron entry. Logs to data/logs/.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

PYTHON="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3}"

{
  echo "=== run started $(date -Iseconds) ==="
  "$PYTHON" -m src.run
  echo "=== run finished $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
