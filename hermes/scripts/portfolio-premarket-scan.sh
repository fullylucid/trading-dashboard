#!/usr/bin/env bash
# portfolio-premarket-scan.sh — Tradeskeebot pre-market portfolio scan
#
# 1. POST /api/portfolio/scan → background job
# 2. Poll GET /api/portfolio/scan/{job_id} every 5s until status=complete
# 3. Extract top 3 buys / top 3 sells / portfolio value
# 4. Narrative one-liner via kimi-k2.6:cloud (Ollama Cloud)
# 5. Send Telegram message to @Siiigggbot
#
# Cron: 3:30 AM PT daily (Mon–Fri).
set -uo pipefail

# --- config ---
API_BASE="${API_BASE:-https://shaptech-3p3qo.ondigitalocean.app}"
TOP_N="${TOP_N:-10}"
INCLUDE_THESIS="${INCLUDE_THESIS:-true}"
MAX_POLLS="${MAX_POLLS:-40}"   # 40 * 5s = 200s max wait
SLEEP_SEC="${SLEEP_SEC:-5}"

TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-5696824719}"
TELEGRAM_BOT_TOKEN_DEFAULT="8398668205:AAGFHkw8b9YMtRYDsm-7sm67LkLg-OUmTjA"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$TELEGRAM_BOT_TOKEN_DEFAULT}"

LOG_DIR="${HOME}/.hermes/logs"
LOG_FILE="${LOG_DIR}/portfolio-premarket-scan.log"
mkdir -p "${LOG_DIR}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load OLLAMA creds from ~/.hermes/.env if not in env
if [[ -z "${OLLAMA_API_KEY:-}" || -z "${OLLAMA_BASE_URL:-}" ]]; then
    if [[ -f "${HOME}/.hermes/.env" ]]; then
        set -a
        # shellcheck disable=SC1091
        source "${HOME}/.hermes/.env"
        set +a
    fi
fi
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-https://ollama.com/v1}"

log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S %Z')
    echo "[${ts}] $*" | tee -a "${LOG_FILE}" >&2
}

send_telegram() {
    local text="$1"
    curl -sS -m 15 \
        -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${text}" \
        -d "parse_mode=Markdown" \
        -d "disable_web_page_preview=true" >/dev/null
}

log "=== pre-market scan start ==="
log "API_BASE=${API_BASE} top_n=${TOP_N} include_thesis=${INCLUDE_THESIS}"

# --- 1. POST scan ---
SCAN_RESP=$(curl -sS -X POST -m 120 \
    "${API_BASE}/api/portfolio/scan?top_n=${TOP_N}&include_thesis=${INCLUDE_THESIS}" \
    2>>"${LOG_FILE}" || echo "")
log "scan POST: ${SCAN_RESP:0:300}"

JOB_ID=$(printf '%s' "${SCAN_RESP}" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("job_id", ""))
except Exception:
    print("")
' 2>/dev/null || echo "")

if [[ -z "${JOB_ID}" ]]; then
    log "ERROR: no job_id"
    send_telegram "🕷️ Tradeskeebot pre-market: ❌ POST /scan returned no job_id." || true
    exit 1
fi
log "job_id=${JOB_ID}"

# --- 2. Poll until complete ---
FINAL_JSON_PATH="/tmp/premarket_scan_${JOB_ID}.json"
: > "${FINAL_JSON_PATH}"
COMPLETE=0
for ((i=1; i<=MAX_POLLS; i++)); do
    sleep "${SLEEP_SEC}"
    POLL=$(curl -sS -m 65 "${API_BASE}/api/portfolio/scan/${JOB_ID}" 2>/dev/null || echo "")
    if [[ -z "${POLL}" ]]; then
        log "poll ${i}: empty response"
        continue
    fi
    STATUS=$(printf '%s' "${POLL}" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("status", "?"))
except Exception:
    print("PARSE_ERR")
' 2>/dev/null || echo "PARSE_ERR")
    log "poll ${i}: status=${STATUS}"
    case "${STATUS}" in
        complete)
            printf '%s' "${POLL}" > "${FINAL_JSON_PATH}"
            COMPLETE=1
            break
            ;;
        error|failed)
            log "ERROR: job ${JOB_ID} reported status=${STATUS}"
            send_telegram "🕷️ Tradeskeebot pre-market: ❌ job ${STATUS}." || true
            exit 1
            ;;
    esac
done

if [[ "${COMPLETE}" -ne 1 ]]; then
    log "ERROR: timed out after ${MAX_POLLS} polls"
    send_telegram "🕷️ Tradeskeebot pre-market: ⏱️ timed out after $((MAX_POLLS*SLEEP_SEC))s." || true
    exit 1
fi

# --- 3. Build message body (and write sidecar CSV with BUYS_CSV/SELLS_CSV/PV) ---
# First call writes sidecar; pass empty narrative to get CSVs out.
PRELIM_MSG=$(python3 "${SCRIPT_DIR}/_format_scan_msg.py" "${FINAL_JSON_PATH}" "" 2>>"${LOG_FILE}")
SIDECAR="${FINAL_JSON_PATH}.csv"
if [[ ! -s "${SIDECAR}" ]]; then
    log "ERROR: sidecar missing — formatter failed"
    send_telegram "🕷️ Tradeskeebot pre-market: ❌ result parse failed." || true
    exit 1
fi
# shellcheck disable=SC1090
BUYS_CSV=""; SELLS_CSV=""; PORTFOLIO_VALUE=""
while IFS='=' read -r k v; do
    case "${k}" in
        BUYS_CSV) BUYS_CSV="${v}" ;;
        SELLS_CSV) SELLS_CSV="${v}" ;;
        PORTFOLIO_VALUE) PORTFOLIO_VALUE="${v}" ;;
    esac
done < "${SIDECAR}"
log "buys=[${BUYS_CSV}] sells=[${SELLS_CSV}] pv=${PORTFOLIO_VALUE}"

# --- 4. Narrative via kimi-k2.6:cloud (Ollama Cloud) ---
# Pull top-buy theses from final JSON to feed kimi.
THESES_BLOCK=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
buys = (d.get("result") or {}).get("top_buys") or []
parts = []
for b in buys[:5]:
    sym = b.get("symbol", "?")
    th = (b.get("thesis_markdown") or "").strip()
    if th:
        parts.append(f"=== {sym} ===\n{th}")
print("\n\n".join(parts))
' "${FINAL_JSON_PATH}" 2>>"${LOG_FILE}" || echo "")
log "theses block chars=${#THESES_BLOCK}"

NARRATIVE=""
if [[ -n "${OLLAMA_API_KEY:-}" ]]; then
    SYS_MSG="You are Jeremy Lefebvre / 1000xstocks-style portfolio narrator. Write a short, punchy, decisive pre-market briefing (3–5 sentences, max ~600 chars total). Reference each top-buy ticker with a one-line take grounded in the supplied thesis (catalyst, edge, or risk). Mention trims/sells in one closing line. No preamble, no headers, no bullet points, no quotes — just flowing prose."
    USR_MSG="Pre-market portfolio summary.
Buys: ${BUYS_CSV}
Sells/trims: ${SELLS_CSV}
Portfolio value: ${PORTFOLIO_VALUE}

Top-buy theses (use these for the per-ticker takes):
${THESES_BLOCK}"
    PAYLOAD=$(python3 -c '
import json, sys
print(json.dumps({
    "model": "kimi-k2.6:cloud",
    "messages": [
        {"role": "system", "content": sys.argv[1]},
        {"role": "user",   "content": sys.argv[2]},
    ],
    "max_tokens": 8192,
    "temperature": 0.6,
}))
' "${SYS_MSG}" "${USR_MSG}")
    OLLAMA_RESP=$(curl -sS -m 120 \
        -H "Authorization: Bearer ${OLLAMA_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "${PAYLOAD}" \
        "${OLLAMA_BASE_URL}/chat/completions" 2>>"${LOG_FILE}" || echo "")
    log "ollama resp (first 300): ${OLLAMA_RESP:0:300}"
    NARRATIVE=$(printf '%s' "${OLLAMA_RESP}" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    c = d["choices"][0]["message"]["content"].strip().strip("\"").strip("'\''")
    # Collapse newlines into one line
    print(" ".join(c.split()))
except Exception:
    print("")
' 2>/dev/null || echo "")
fi

if [[ -z "${NARRATIVE}" ]]; then
    NARRATIVE="Premarket scan complete — ${BUYS_CSV} bid, ${SELLS_CSV} offered."
    log "using fallback narrative"
fi
log "narrative: ${NARRATIVE}"

# --- 5. Final message ---
FINAL_MSG=$(python3 "${SCRIPT_DIR}/_format_scan_msg.py" "${FINAL_JSON_PATH}" "${NARRATIVE}")
log "msg:\n${FINAL_MSG}"

# --- 6. Send Telegram ---
send_telegram "${FINAL_MSG}"
SEND_RC=$?
log "telegram send rc=${SEND_RC}"

# --- 7. Cleanup (keep last 7 days of JSON for debugging) ---
find /tmp -maxdepth 1 -name 'premarket_scan_*.json*' -mtime +7 -delete 2>/dev/null || true

log "=== pre-market scan done ==="
exit 0
