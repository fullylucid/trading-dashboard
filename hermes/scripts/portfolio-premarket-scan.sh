#!/usr/bin/env bash
# Pre-market portfolio scan using the background job endpoint.
# Posts a clean Telegram alert with top buys, sells, portfolio value, and a one-line narrative.
set -euo pipefail

LOG_DIR="/home/user/.hermes/logs"
LOG_FILE="${LOG_DIR}/portfolio-premarket-scan.log"
mkdir -p "${LOG_DIR}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" >> "${LOG_FILE}"
}

log "=== portfolio-premarket-scan start ==="

# --- 1. Reuse Telegram creds from trading-alerts.sh ---
ALERTS_SH="/home/user/.hermes/workspace/trading-dashboard/hermes/scripts/trading-alerts.sh"
if [[ ! -f "${ALERTS_SH}" ]]; then
    log "ERROR: ${ALERTS_SH} not found; cannot source Telegram creds"
    exit 1
fi
TG_CREDS="$(grep -E '^(TELEGRAM_TOKEN|TELEGRAM_CHAT_ID)=' "${ALERTS_SH}" || true)"
if [[ -z "${TG_CREDS}" ]]; then
    log "ERROR: could not extract TELEGRAM_TOKEN/TELEGRAM_CHAT_ID from ${ALERTS_SH}"
    exit 1
fi
eval "${TG_CREDS}"

# --- 2. Load Ollama env ---
ENV_FILE="/home/user/.hermes/.env"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

API_BASE="https://shaptech-3p3qo.ondigitalocean.app"

# Telegram send helper
send_telegram() {
    local text="$1"
    local resp
    resp=$(curl -sS -X POST -m 20 \
        "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${text}" \
        --data-urlencode "parse_mode=Markdown" 2>&1 || echo "CURL_FAIL")
    log "Telegram response: ${resp}"
    if [[ "${resp}" == *"\"ok\":true"* ]]; then
        return 0
    fi
    return 1
}

# --- 3. Kick off the scan job ---
log "POST ${API_BASE}/api/portfolio/scan?top_n=15&include_thesis=false"
SCAN_RESP=$(curl -sS -X POST -m 30 \
    "${API_BASE}/api/portfolio/scan?top_n=15&include_thesis=false" 2>&1 || echo "")
log "scan POST response: ${SCAN_RESP}"

JOB_ID=$(printf '%s' "${SCAN_RESP}" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get("job_id",""))
except Exception:
    print("")' 2>/dev/null || echo "")

if [[ -z "${JOB_ID}" ]]; then
    log "ERROR: no job_id in scan response"
    send_telegram "🕷️ Tradeskeebot pre-market scan: ❌ failed to enqueue scan job." || true
    exit 1
fi
log "job_id=${JOB_ID}"

# --- 4. Poll ---
MAX_POLLS=40
SLEEP_SEC=5
FINAL_JSON=""
for ((i=1; i<=MAX_POLLS; i++)); do
    sleep "${SLEEP_SEC}"
    POLL=$(curl -sS -m 15 "${API_BASE}/api/portfolio/scan/${JOB_ID}" 2>&1 || echo "")
    if [[ -z "${POLL}" ]]; then
        log "[poll ${i}] empty/failed response, continuing"
        continue
    fi
    STATUS_LINE=$(printf '%s' "${POLL}" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    st=d.get("status","?")
    p=d.get("progress") or {}
    print(f"{st}|{p.get(\"scanned\",0)}|{p.get(\"total\",0)}")
except Exception as e:
    print(f"PARSE_ERR|0|0")' 2>/dev/null || echo "PARSE_ERR|0|0")
    IFS='|' read -r STATUS SCANNED TOTAL <<< "${STATUS_LINE}"
    log "[poll ${i}] status=${STATUS} progress=${SCANNED}/${TOTAL}"

    if [[ "${STATUS}" == "complete" ]]; then
        FINAL_JSON="${POLL}"
        break
    elif [[ "${STATUS}" == "error" ]]; then
        log "ERROR: scan job ${JOB_ID} returned status=error"
        send_telegram "🕷️ Tradeskeebot pre-market scan: ❌ scan job errored." || true
        exit 1
    fi
done

if [[ -z "${FINAL_JSON}" ]]; then
    log "ERROR: scan timed out after ${MAX_POLLS} polls"
    send_telegram "🕷️ Tradeskeebot pre-market scan: ⏱️ timed out after ${MAX_POLLS} polls." || true
    exit 1
fi

# --- 5. Extract fields ---
EXTRACT=$(printf '%s' "${FINAL_JSON}" | python3 <<'PY' 2>/dev/null || echo ""
import json, sys
try:
    d = json.load(sys.stdin)
    result = d.get("result") or {}
    pv = result.get("portfolio_value")
    try:
        pv_f = float(pv)
        pv_str = "${:,.2f}".format(pv_f)
    except Exception:
        pv_str = "$0.00"
    buys = result.get("buys") or []
    sells = result.get("sells") or []
    def fmt(items):
        lines=[]
        csv=[]
        for it in items[:3]:
            sym = it.get("symbol","?")
            sc = it.get("composite_score", 0)
            try:
                sc_f = float(sc)
            except Exception:
                sc_f = 0.0
            lines.append(f"• {sym}  {sc_f:.2f}")
            csv.append(sym)
        return "\n".join(lines), ", ".join(csv)
    bblock, bcsv = fmt(buys)
    sblock, scsv = fmt(sells)
    def shq(s):
        # single-quote escape for bash eval
        return "'" + s.replace("'", "'\"'\"'") + "'"
    print(f"PORTFOLIO_VALUE={shq(pv_str)}")
    print(f"BUYS_BLOCK={shq(bblock)}")
    print(f"SELLS_BLOCK={shq(sblock)}")
    print(f"BUYS_CSV={shq(bcsv)}")
    print(f"SELLS_CSV={shq(scsv)}")
except Exception as e:
    sys.stderr.write(f"extract err: {e}\n")
    sys.exit(1)
PY
)

if [[ -z "${EXTRACT}" ]]; then
    log "ERROR: failed to extract fields from final JSON"
    send_telegram "🕷️ Tradeskeebot pre-market scan: ❌ result parse failed." || true
    exit 1
fi
log "extracted: ${EXTRACT}"
eval "${EXTRACT}"

# --- 6. Narrative via Ollama Cloud (kimi-k2.6:cloud) ---
NARRATIVE=""
if [[ -n "${OLLAMA_API_KEY:-}" && -n "${OLLAMA_BASE_URL:-}" ]]; then
    SYS_MSG="You are Jeremy Lefebvre / 1000xstocks-style market analyst. Reply with EXACTLY ONE punchy sentence, ≤140 chars, no preamble, no quotes."
    USR_MSG="Pre-market portfolio summary. Buys: ${BUYS_CSV}. Sells/trims: ${SELLS_CSV}. Portfolio value: ${PORTFOLIO_VALUE}. Write one line."
    PAYLOAD=$(python3 -c '
import json, sys
sys_msg = sys.argv[1]
usr_msg = sys.argv[2]
print(json.dumps({
    "model": "kimi-k2.6:cloud",
    "messages": [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": usr_msg}
    ],
    "max_tokens": 8192,
    "temperature": 0.7
}))' "${SYS_MSG}" "${USR_MSG}")

    OLLAMA_RESP=$(curl -sS -m 60 -X POST \
        -H "Authorization: Bearer ${OLLAMA_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "${PAYLOAD}" \
        "${OLLAMA_BASE_URL}/chat/completions" 2>&1 || echo "")
    log "ollama response (first 500): ${OLLAMA_RESP:0:500}"

    NARRATIVE=$(printf '%s' "${OLLAMA_RESP}" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    c = d["choices"][0]["message"]["content"]
    print(c.strip().strip("\"").strip("'"'"'"))
except Exception:
    print("")' 2>/dev/null || echo "")
fi

if [[ -z "${NARRATIVE}" ]]; then
    NARRATIVE="Premarket scan complete — ${BUYS_CSV} bid, ${SELLS_CSV} offered."
    log "using fallback narrative"
fi
log "narrative: ${NARRATIVE}"

# --- 7. Compose & send Telegram message ---
NOW=$(TZ=America/Los_Angeles date '+%Y-%m-%d %H:%M PT')
MSG=$(printf '🕷️ Tradeskeebot — Pre-Market Scan\n%s\n\n💼 Portfolio: %s\n\n🟢 *Top Buys*\n%s\n\n🔴 *Top Trims / Sells*\n%s\n\n🧠 %s\n' \
    "${NOW}" "${PORTFOLIO_VALUE}" "${BUYS_BLOCK}" "${SELLS_BLOCK}" "${NARRATIVE}")

log "sending Telegram message..."
if send_telegram "${MSG}"; then
    log "Telegram send OK"
else
    log "ERROR: Telegram send failed"
    exit 1
fi

log "=== portfolio-premarket-scan done ==="
