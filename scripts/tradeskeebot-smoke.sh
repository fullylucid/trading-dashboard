#!/bin/bash
# Tradeskeebot smoke test — verify DO backend is alive + key endpoints respond.
# Silent on success (no output). Loud on failure (prints + exits non-zero).
# Designed to be cron-friendly with no_agent watchdog pattern.

set -u
BASE="${BASE:-https://shaptech-3p3qo.ondigitalocean.app}"
TIMEOUT="${TIMEOUT:-20}"
FAIL=()

check() {
  local name="$1" url="$2" expect="$3"
  local code
  code=$(curl -sS -m "$TIMEOUT" -o /tmp/smoke.body -w "%{http_code}" "$url" 2>/dev/null) || code="000"
  code="${code:-000}"
  if [[ "$code" != "200" ]]; then
    FAIL+=("$name HTTP=$code url=$url")
    return
  fi
  if [[ -n "$expect" ]] && ! grep -q "$expect" /tmp/smoke.body; then
    FAIL+=("$name body missing '$expect'")
  fi
}

check "root"          "$BASE/"                                ''
check "portal-health" "$BASE/api/portal/health"               '"status":"ok"'
check "pltr-proj"     "$BASE/api/research/projections/PLTR"   'PLTR'

if [[ ${#FAIL[@]} -gt 0 ]]; then
  echo "🚨 Tradeskeebot smoke FAILED $(date -Iseconds)"
  echo "Base: $BASE"
  for f in "${FAIL[@]}"; do echo "  - $f"; done
  exit 1
fi
exit 0
