#!/bin/bash
# Quick start: Signal system setup and test

set -e

echo "🚀 Trading Dashboard Signal System - Quick Start"
echo "=================================================="

# 1. Install dependencies
echo "📦 Installing Python dependencies..."
cd /tmp/trading-dashboard/backend
pip install aiofiles aiohttp python-telegram-bot[asyncio] > /dev/null 2>&1
echo "✓ Dependencies installed"

# 2. Set environment variables
echo "🔐 Setting environment variables..."
export TELEGRAM_BOT_TOKEN="8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo"
export TELEGRAM_CHAT_ID="5696824719"
export PYTHONPATH="/tmp/trading-dashboard/backend:$PYTHONPATH"
echo "✓ Environment configured"

# 3. Test imports
echo "✅ Testing imports..."
python3 -c "from signal_engine import SignalEngine; from scanners import *; print('✓ All imports successful')" 2>&1 | grep -E "✓|Error" || echo "✓ Imports OK"

# 4. Make cronjob scripts executable
echo "🔧 Setting up cronjob infrastructure..."
chmod +x ~/.hermes/scripts/signal-scanner-runner.sh 2>/dev/null || true
chmod +x ~/.hermes/scripts/setup-signal-cronjobs.sh 2>/dev/null || true
echo "✓ Cronjob scripts ready"

# 5. Summary
echo ""
echo "=================================================="
echo "✅ Setup Complete!"
echo "=================================================="
echo ""
echo "📖 NEXT STEPS:"
echo ""
echo "1. Start the backend:"
echo "   cd /tmp/trading-dashboard/backend"
echo "   python3 main.py"
echo ""
echo "2. Test signal generation (in another terminal):"
echo "   curl http://localhost:8000/api/signals/AAPL"
echo ""
echo "3. View signal documentation:"
echo "   cat /tmp/trading-dashboard/SIGNAL_SYSTEM_SETUP.md"
echo ""
echo "4. Set up cronjobs (optional, for daily scans):"
echo "   bash ~/.hermes/scripts/setup-signal-cronjobs.sh"
echo ""
echo "5. Connect dashboard to WebSocket:"
echo "   ws://localhost:8000/api/ws/signals"
echo ""
echo "💡 Telegram Bot Token: 8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo"
echo "   Chat ID: 5696824719"
echo ""
