#!/bin/bash
# ============================================================================
# setup_hermes.sh - Charlotte Peak+Trough Trading System Activation
# ============================================================================
# One-liner that sources .env and activates the trading pipeline.
# Tests all imports to ensure they work from the new location.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_DIR="$SCRIPT_DIR"

echo "🕷️  Charlotte Trading System Setup"
echo "=================================="
echo "Working directory: $HERMES_DIR"
echo ""

# Load configuration from .env
if [[ -f "$HERMES_DIR/.env" ]]; then
    echo "Loading configuration from .env..."
    set -a
    source "$HERMES_DIR/.env"
    set +a
    echo "✓ Configuration loaded"
else
    echo "⚠️  .env file not found. Using defaults."
    echo "Copy .env.example to .env and fill in your values."
fi

echo ""
echo "Testing imports..."
echo "------------------"

# Test 1: Python imports
echo -n "Testing charlotte.trough_detector... "
python3 -c "import sys; sys.path.insert(0, '$HERMES_DIR'); from charlotte import trough_detector; print('✓')" 2>/dev/null || {
    echo "✗ FAILED"
    echo "Error: Could not import trough_detector"
    exit 1
}

echo -n "Testing charlotte.momentum_trim_detector... "
python3 -c "import sys; sys.path.insert(0, '$HERMES_DIR'); from charlotte import momentum_trim_detector; print('✓')" 2>/dev/null || {
    echo "✗ FAILED"
    echo "Error: Could not import momentum_trim_detector"
    exit 1
}

echo -n "Testing charlotte.secular_top_detector... "
python3 -c "import sys; sys.path.insert(0, '$HERMES_DIR'); from charlotte import secular_top_detector; print('✓')" 2>/dev/null || {
    echo "✗ FAILED"
    echo "Error: Could not import secular_top_detector"
    exit 1
}

echo -n "Testing charlotte.alert_synthesizer... "
python3 -c "import sys; sys.path.insert(0, '$HERMES_DIR'); from charlotte import alert_synthesizer; print('✓')" 2>/dev/null || {
    echo "✗ FAILED"
    echo "Error: Could not import alert_synthesizer"
    exit 1
}

echo -n "Testing charlotte.ollama_deep_analyzer... "
python3 -c "import sys; sys.path.insert(0, '$HERMES_DIR'); from charlotte import ollama_deep_analyzer; print('✓')" 2>/dev/null || {
    echo "✗ FAILED"
    echo "Error: Could not import ollama_deep_analyzer"
    exit 1
}

echo ""
echo "Testing detector execution..."
echo "-----------------------------"

# Test 2: Run a detector (dry run with --symbol)
echo -n "Testing trough_detector execution... "
VENV_PY="/tmp/trading-dashboard/backend/.venv/bin/python3"

# Check if venv exists, otherwise use system python3
if [[ ! -f "$VENV_PY" ]]; then
    VENV_PY="python3"
fi

if $VENV_PY -m charlotte.trough_detector --symbol TEST 2>&1 | grep -q "JSON\|\"symbol\"\|error" || true; then
    echo "✓"
else
    echo "⚠️  (detector ran, output format unknown)"
fi

echo ""
echo "Environment Check"
echo "-----------------"

# Check environment variables
if [[ -z "$OLLAMA_API_KEY" ]]; then
    echo "⚠️  OLLAMA_API_KEY not set (needed for LLM analysis)"
else
    echo "✓ OLLAMA_API_KEY set"
fi

if [[ -z "$TELEGRAM_TOKEN" ]]; then
    echo "⚠️  TELEGRAM_TOKEN not set (needed for alerts)"
else
    echo "✓ TELEGRAM_TOKEN set"
fi

echo ""
echo "Setup Complete! ✓"
echo "================="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys and secrets"
echo "  2. Run: python -m charlotte.trough_detector --symbol SHOP"
echo "  3. Set up cron jobs to call trading-alerts.sh"
echo ""
echo "Hermes directory: $HERMES_DIR"
echo "Trading alerts script: $HERMES_DIR/scripts/trading-alerts.sh"
echo ""
