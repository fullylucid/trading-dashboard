#!/bin/bash

# Unified alert system: Charlotte Peak+Trough + System monitoring
# Sends alerts to Telegram via @Siiigggbot
# Runs on cron schedule: premarket 6:30 AM, market open 9:30 AM, hourly 10-3 PM, after-hours 4:15 PM ET

set -e

LOG_DIR="/home/user/.hermes/logs"
LOG_FILE="$LOG_DIR/trading-alerts.log"
HERMES_DIR="/home/user/.hermes/workspace/trading-dashboard/hermes"
VENV_PY="/home/user/.hermes/workspace/trading-dashboard/backend/venv/bin/python3"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
TIMESTAMP_UNIX=$(date +%s)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Alert thresholds
SYS_CPU_THRESHOLD=75
SYS_MEM_THRESHOLD=80
SYS_DISK_THRESHOLD=90
MIN_SIGNAL_CONFIDENCE=6.0

# Telegram config - send to @Siiigggbot trading bot
TELEGRAM_TOKEN="8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo"  # @Siiigggbot token
TELEGRAM_CHAT_ID="5696824719"  # Schyler's user ID (bot sends here)

# Core watchlist (these are always scanned by Charlotte)
WATCHLIST=("SHOP" "SOFI" "COIN" "SMCI" "CRDO" "GLW" "GFS" "AMD" "PLTR" "INTC" "USAR" "AMSC" "XNDU" "NBIS")

# ============================================================================
# CHARLOTTE SIGNALS (Peak + Trough Analysis v3.2)
# ============================================================================

CHARLOTTE_ALERT=""

if [[ -d "$HERMES_DIR" ]]; then
    cd "$HERMES_DIR"
    
    # Run Charlotte detectors and format alerts
    CHARLOTTE_ALERT=$("$VENV_PY" << 'PYTHONEOF'
import sys
import json
import subprocess
import math

signals = []
detectors = [
    "charlotte.trough_detector",
    "charlotte.momentum_trim_detector", 
    "charlotte.secular_top_detector"
]

symbols = ["SHOP", "SOFI", "COIN", "SMCI", "CRDO", "GLW", "GFS", "AMD", "PLTR", "INTC", "USAR", "AMSC", "XNDU", "NBIS"]
min_conf = 6.0

try:
    for detector in detectors:
        try:
            result = subprocess.run(
                [sys.executable, "-m", detector, "--symbol"] + symbols,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0 and result.stdout:
                try:
                    detector_signals = json.loads(result.stdout)
                    signals.extend(detector_signals)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            pass
    
    # Filter by confidence
    high_conf = [s for s in signals if s.get("confidence", 0) >= min_conf]
    
    if not high_conf:
        sys.exit(0)
    
    # Group by category
    by_cat = {}
    for sig in high_conf:
        cat = sig.get("category", "unknown")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(sig)
    
    output = []
    
    # Troughs (green buy signals)
    if "trough" in by_cat:
        output.append("🟢 **ADD OPPORTUNITIES (Troughs)**")
        for sig in sorted(by_cat["trough"], key=lambda x: x.get("confidence", 0), reverse=True):
            sym = sig.get("symbol", "?")
            conf = sig.get("confidence", 0)
            reasons = " + ".join(sig.get("reasons", [])[:2])
            add_pct = sig.get("add_pct", 10)
            output.append(f"  • {sym} (conf {conf:.1f}/10)")
            output.append(f"    Reasons: {reasons}")
            output.append(f"    Action: Add {add_pct}% to core")
        output.append("")
    
    # Secular tops (orange thesis review)
    if "secular_top" in by_cat:
        output.append("🟠 **THESIS REVIEWS (Secular Tops)**")
        for sig in sorted(by_cat["secular_top"], key=lambda x: x.get("confidence", 0), reverse=True):
            sym = sig.get("symbol", "?")
            conf = sig.get("confidence", 0)
            reasons = " + ".join(sig.get("reasons", [])[:2])
            trim_pct = sig.get("trim_pct", 50)
            output.append(f"  • {sym} (conf {conf:.1f}/10)")
            output.append(f"    Reasons: {reasons}")
            output.append(f"    Action: Trim {trim_pct}% + review thesis")
        output.append("")
    
    # Momentum trims (red exit signals)
    if "momentum_trim" in by_cat:
        output.append("🔴 **TRIM PEAKS (Momentum)**")
        for sig in sorted(by_cat["momentum_trim"], key=lambda x: x.get("confidence", 0), reverse=True):
            sym = sig.get("symbol", "?")
            conf = sig.get("confidence", 0)
            reasons = " + ".join(sig.get("reasons", [])[:2])
            trim_pct = sig.get("trim_pct", 30)
            trail_pct = sig.get("trail_pct", 10)
            output.append(f"  • {sym} (conf {conf:.1f}/10)")
            output.append(f"    Reasons: {reasons}")
            output.append(f"    Action: Trim {trim_pct}%, trail {trail_pct}%")
        output.append("")
    
    if output:
        print("\n".join(output).strip())

except Exception as e:
    pass

PYTHONEOF
    )
fi

# ============================================================================
# SYSTEM ALERTS
# ============================================================================

CPU_IDLE=$(top -bn1 | grep "Cpu(s)" | awk '{print int($8)}')
CPU_ACTIVE=$((100 - CPU_IDLE))
MEM_INFO=$(free | grep Mem)
MEM_TOTAL=$(echo $MEM_INFO | awk '{print $2}')
MEM_USED=$(echo $MEM_INFO | awk '{print $3}')
MEM_PERCENT=$(( (MEM_USED * 100) / MEM_TOTAL ))
DISK_USAGE=$(df -h / | tail -1 | awk '{print $5}' | sed 's/%//')

# ============================================================================
# LOG ENTRY
# ============================================================================

LOG_ENTRY="[$TIMESTAMP] Scanned ${#WATCHLIST[@]} symbols | SYS: CPU=${CPU_ACTIVE}% Mem=${MEM_PERCENT}% Disk=${DISK_USAGE}%"
echo "$LOG_ENTRY" >> "$LOG_FILE"

# ============================================================================
# BUILD CONSOLIDATED ALERT
# ============================================================================

ALERT=""

# Charlotte trading signals (priority)
if [[ -n "$CHARLOTTE_ALERT" ]]; then
    ALERT="${CHARLOTTE_ALERT}"
fi

# System health alerts (only if critical)
if [[ $CPU_ACTIVE -gt $SYS_CPU_THRESHOLD ]]; then
    if [[ -z "$ALERT" ]]; then
        ALERT="🔴 CPU SPIKE: ${CPU_ACTIVE}%"
    else
        ALERT="${ALERT}\n🔴 CPU SPIKE: ${CPU_ACTIVE}%"
    fi
fi
if [[ $MEM_PERCENT -gt $SYS_MEM_THRESHOLD ]]; then
    if [[ -z "$ALERT" ]]; then
        ALERT="🔴 MEMORY: ${MEM_PERCENT}%"
    else
        ALERT="${ALERT}\n🔴 MEMORY: ${MEM_PERCENT}%"
    fi
fi
if [[ $DISK_USAGE -gt $SYS_DISK_THRESHOLD ]]; then
    if [[ -z "$ALERT" ]]; then
        ALERT="🔴 DISK: ${DISK_USAGE}%"
    else
        ALERT="${ALERT}\n🔴 DISK: ${DISK_USAGE}%"
    fi
fi

# ============================================================================
# SEND TO TELEGRAM
# ============================================================================

if [[ -n "$ALERT" ]]; then
    # Format for Telegram
    NOW=$(date '+%Y-%m-%d %H:%M ET')
    MESSAGE="🕷️ Charlotte — $NOW

${ALERT}"
    
    # Send to Telegram
    if [[ -n "$TELEGRAM_TOKEN" ]] && [[ "$TELEGRAM_TOKEN" != "null" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${MESSAGE}" \
            -d "parse_mode=Markdown" > /dev/null 2>&1 || true
        
        # Log send
        echo "[$TIMESTAMP] Alert sent to Telegram" >> "$LOG_FILE"
    fi
    
    # Also output to console (for debugging)
    echo -e "$MESSAGE"
else
    # Silent when no alerts (preserve resources)
    echo "[$TIMESTAMP] No signals above confidence threshold (6.0)"
fi
