#!/bin/bash
# Daily refresh: rerun the pipeline, then push the updated docs/ to GitHub
# so the public Pages site shows the latest fair-vs-market table.
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

  if git diff --quiet -- docs/; then
    echo "docs/ unchanged — nothing to publish."
  else
    git add docs/
    git -c user.name="$(git config user.name)" \
        -c user.email="$(git config user.email)" \
        commit -m "Daily refresh: $(date +%Y-%m-%d)"
    git push origin main
    echo "Published to https://gehrenberg823.github.io/mlb-playoff-odds/"
  fi

  echo "=== run finished $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
