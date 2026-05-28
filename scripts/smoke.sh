#!/bin/bash
# Tradeskeebot smoke test — verify backend is alive + key endpoints respond.
# Silent on success (no output). Loud on failure (prints + exits non-zero).
# Designed to be cron-friendly with no_agent watchdog pattern.

set -u
BASE="${BASE:-http://127.0.0.1:8000}"
FAIL=()

check() {
  local name="$1" url="$2" expect="$3"
  local body code
  body=$(curl -sS -m 8 -o /tmp/smoke.body -w "%{http_code}" "$url" 2>/dev/null) || code=000
  code="${body:-000}"
  if [[ "$code" != "200" ]]; then
    FAIL+=("$name HTTP=$code url=$url")
    return
  fi
  if [[ -n "$expect" ]] && ! grep -q "$expect" /tmp/smoke.body; then
    FAIL+=("$name body missing '$expect'")
  fi
}

check "root"          "$BASE/"                            '"title"'
check "portal-health" "$BASE/api/portal/health"           '"status":"ok"'
check "pltr-proj"     "$BASE/api/research/projections/PLTR" 'PLTR'

# Cron freshness: trading-alerts.log touched in last 24h on weekdays
LOG=/home/user/.hermes/logs/trading-alerts.log
if [[ $(date +%u) -le 5 ]] && [[ -f "$LOG" ]]; then
  AGE=$(( $(date +%s) - $(stat -c %Y "$LOG") ))
  if [[ $AGE -gt 86400 ]]; then
    FAIL+=("trading-alerts.log stale ${AGE}s")
  fi
fi

if [[ ${#FAIL[@]} -gt 0 ]]; then
  echo "🚨 Tradeskeebot smoke FAILED $(date -Iseconds)"
  for f in "${FAIL[@]}"; do echo "  - $f"; done
  exit 1
fi
exit 0
