#!/usr/bin/env bash
# Supervised backend launcher for Charlotte / Hermes Portal / Phase 2.
# Idempotent: kills any prior uvicorn for this app, then execs a fresh one.
# Designed to be invoked from cron (@reboot) or by hand.
set -euo pipefail

REPO=/home/user/.hermes/workspace/trading-dashboard
LOG_DIR=/home/user/.hermes/logs
mkdir -p "$LOG_DIR"

# Load secrets if .env exists
if [[ -f "$REPO/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO/.env"
  set +a
fi

# Kill prior uvicorn cleanly
pkill -f "uvicorn.*main:app.*--port 8000" 2>/dev/null || true
sleep 1

cd "$REPO/backend"
# shellcheck disable=SC1091
source venv/bin/activate

export PYTHONPATH="$REPO:$REPO/hermes"

exec python -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
