#!/usr/bin/env bash
# sector-rotation-digest.sh — Tradeskeebot daily sector-rotation digest
#
# 1. GET /api/sector-rotation?refresh=true  -> runs the 5-stream sweep server-side
#    (price/RRG + SEC Form-4 smart money + Finnhub news + earnings/FRED catalysts
#    + congressional/USAspending policy), fused into a per-sector rotation score,
#    and persists the snapshot the dashboard + portfolio scan read.
# 2. Format the top rotating-IN / rotating-OUT sectors + affected holdings
#    (tailwinds/risks) + candidate tickers into a compact digest.
# 3. Send Telegram message to @Siiigggbot (Signals bot).
#
# Cron suggestion: 4:00 AM PT daily (after the pre-market scan), Mon–Fri.
# Zero LLM tokens — pure script + the server-side sweep (free data sources).
set -uo pipefail

# --- config ---
API_BASE="${API_BASE:-https://shaptech-3p3qo.ondigitalocean.app}"
HTTP_TIMEOUT="${HTTP_TIMEOUT:-300}"   # the sweep fans out across 5 networked streams

# Telegram delivery — same Signals bot (@Siiigggbot) the pre-market scan uses.
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-5696824719}"
SIGNALS_BOT_TOKEN_DEFAULT="8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo"
TELEGRAM_BOT_TOKEN="${SIGNALS_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-$SIGNALS_BOT_TOKEN_DEFAULT}}"

LOG_DIR="${HOME}/.hermes/logs"
LOG_FILE="${LOG_DIR}/sector-rotation-digest.log"
mkdir -p "${LOG_DIR}"

log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S %Z')
    echo "[${ts}] $*" | tee -a "${LOG_FILE}" >&2
}

send_telegram() {
    local text="$1"
    local resp
    resp=$(curl -sS -m 15 \
        -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${text}" \
        -d "parse_mode=Markdown" \
        -d "disable_web_page_preview=true")
    if [[ "${resp}" == *'"ok":true'* ]]; then
        log "telegram api ok"
        return 0
    else
        log "telegram api FAILED: ${resp:0:200}"
        return 1
    fi
}

log "=== sector-rotation digest start ==="
log "API_BASE=${API_BASE}"

# --- 1. Trigger + fetch the sweep (refresh=true forces a fresh sweep + snapshot) ---
RESP_PATH="/tmp/sector_rotation_digest_$(date +%Y%m%d).json"
HTTP_CODE=$(curl -sS -m "${HTTP_TIMEOUT}" -o "${RESP_PATH}" -w '%{http_code}' \
    "${API_BASE}/api/sector-rotation?refresh=true" 2>>"${LOG_FILE}" || echo "000")
log "GET /api/sector-rotation -> HTTP ${HTTP_CODE}"

if [[ "${HTTP_CODE}" != "200" || ! -s "${RESP_PATH}" ]]; then
    log "ERROR: sweep request failed (HTTP ${HTTP_CODE})"
    send_telegram "🕷️ Tradeskeebot sector rotation: ❌ sweep request failed (HTTP ${HTTP_CODE})." || true
    exit 1
fi

# --- 2. Format the digest (pure python, no LLM) ---
MSG=$(python3 - "${RESP_PATH}" <<'PY'
import json, sys

try:
    data = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"PARSE_ERROR: {e}")
    sys.exit(0)

result = (data.get("result") or {})
summary = (result.get("summary") or {})
sources = summary.get("sources_ok") or {}

def fmt_sector(r):
    sec = r.get("sector") or "?"
    etf = r.get("etf") or ""
    score = r.get("rotation_score")
    conf = r.get("confidence")
    phase = r.get("phase") or ""
    tag = f"{sec}"
    if etf:
        tag += f" ({etf})"
    bits = []
    if score is not None:
        bits.append(f"score {score:+.0f}")
    if conf is not None:
        bits.append(f"conf {conf:.0f}")
    if phase:
        bits.append(phase)
    return f"{tag} — " + ", ".join(bits) if bits else tag

rin = summary.get("rotating_in") or []
rout = summary.get("rotating_out") or []
tailwinds = summary.get("holding_tailwinds") or []
risks = summary.get("holding_risks") or []
alerts = summary.get("alerts") or []
top_in = summary.get("top_in_sectors") or []

lines = ["🕷️ *Sector Rotation Digest*"]

if alerts:
    lines.append("")
    lines.append("🚨 *Immediate alerts:*")
    for r in alerts[:5]:
        lines.append("• " + fmt_sector(r))

lines.append("")
lines.append("🟢 *Rotating IN:*")
if rin:
    for r in rin[:5]:
        lines.append("• " + fmt_sector(r))
else:
    lines.append("• none")

lines.append("")
lines.append("🔴 *Rotating OUT:*")
if rout:
    for r in rout[:5]:
        lines.append("• " + fmt_sector(r))
else:
    lines.append("• none")

if tailwinds:
    lines.append("")
    lines.append("📈 *Holdings with tailwind:* " + ", ".join(tailwinds[:15]))
if risks:
    lines.append("")
    lines.append("⚠️ *Holdings at risk:* " + ", ".join(risks[:15]))

# Candidate tickers in the strongest rotating-IN sectors.
cands = []
for s in top_in[:3]:
    ct = s.get("candidate_tickers") or []
    if ct:
        cands.append(f"{s.get('sector','?')}: " + ", ".join(ct[:6]))
if cands:
    lines.append("")
    lines.append("🎯 *Candidates (rotating-IN sectors):*")
    for c in cands:
        lines.append("• " + c)

# Data-source coverage footer so a degraded sweep is visible at a glance.
ok = [k for k, v in sources.items() if v]
down = [k for k, v in sources.items() if not v]
foot = f"_sources: {len(ok)}/{len(sources)} live"
if down:
    foot += f" (down: {', '.join(down)})"
foot += f" · {summary.get('n_sectors_scored', 0)} sectors_"
lines.append("")
lines.append(foot)

print("\n".join(lines))
PY
)

if [[ -z "${MSG}" || "${MSG}" == PARSE_ERROR:* ]]; then
    log "ERROR: formatter failed: ${MSG:0:200}"
    send_telegram "🕷️ Tradeskeebot sector rotation: ❌ result parse failed." || true
    exit 1
fi
log "digest message:\n${MSG}"

# --- 3. Send Telegram ---
send_telegram "${MSG}"
SEND_RC=$?
log "telegram send rc=${SEND_RC}"

# --- 4. Cleanup (keep last 7 days of JSON for debugging) ---
find /tmp -maxdepth 1 -name 'sector_rotation_digest_*.json' -mtime +7 -delete 2>/dev/null || true

log "=== sector-rotation digest done ==="
exit 0
