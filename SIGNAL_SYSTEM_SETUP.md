# Trading Dashboard Signal System - Setup & Operations

## Overview

Complete **multi-scanner signal generation pipeline** integrated into the FastAPI backend:

- **8 Specialized Scanners** (Smart Money, Options, SEC, Sentiment, Short Interest, News, Technical, Quant Ensemble)
- **Telegram Bot** (8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo) for daily alerts
- **WebSocket Streaming** (real-time signal delivery to dashboard)
- **Signal API** (GET endpoints for signals, scanner details, history)
- **Scheduled Cronjobs** (pre-market, open, hourly, after-hours scans)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│         FastAPI Backend (main.py)                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Signal Engine (signal_engine.py)                       │
│  ├─ Parallel Scanner Execution                          │
│  ├─ Weighted Signal Aggregation                         │
│  ├─ Circuit Breaker (fault tolerance)                   │
│  └─ Redis Caching                                       │
│                                                          │
│  Scanners (scanners/)                                   │
│  ├─ SmartMoney    (institutional patterns)              │
│  ├─ Options       (volume, skew, delta)                 │
│  ├─ SEC           (Form 4, 8-K filings)                 │
│  ├─ Sentiment     (StockTwits, news)                    │
│  ├─ ShortInterest (short float, squeeze)                │
│  ├─ News          (earnings, catalysts)                 │
│  ├─ Technical     (MA, RSI, MACD, patterns)             │
│  └─ QuantEnsemble (7-strategy consensus)                │
│                                                          │
│  Signal Routes (signal_routes.py)                       │
│  ├─ GET /api/signals/                                   │
│  ├─ GET /api/signals/{symbol}                           │
│  ├─ GET /api/signals/{symbol}/history                   │
│  ├─ GET /api/scanner/{scanner_type}                     │
│  └─ POST /api/telegram/webhook                          │
│                                                          │
│  WebSocket Manager (websocket_manager.py)               │
│  ├─ Real-time signal streaming (WS /api/ws)             │
│  ├─ Dynamic subscriptions                               │
│  └─ Client lifecycle management                         │
│                                                          │
│  Telegram Bot (telegram_bot.py)                         │
│  ├─ Async message queue                                 │
│  ├─ Retry logic (exponential backoff)                   │
│  └─ Webhook command handling                            │
│                                                          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │   Telegram Home Chat   │
              │  (Signal Alerts)       │
              └────────────────────────┘
              
              ┌────────────────────────┐
              │  React Dashboard       │
              │  (Live Charts +        │
              │   Signal Feed)         │
              └────────────────────────┘
```

---

## Signal Model

Each signal includes complete component breakdown:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-05-24T14:32:15Z",
  "symbol": "AAPL",
  "signal": "buy",
  "confidence": 72,
  "price": 150.23,
  "scanners_used": ["quant_ensemble", "smart_money", "options"],
  "components": {
    "quant_ensemble": {
      "score": 0.65,
      "momentum": 0.8,
      "mean_reversion": -0.30,
      "volatility_regime": "normal",
      "pattern": "gap_and_go",
      "regime": "bull_calm"
    },
    "smart_money": {
      "insider_buys_30d": 3,
      "position_concentration": 0.82,
      "volume_ratio": 1.45,
      "confidence": 68
    },
    "options": {
      "unusual_volume": true,
      "put_call_ratio": 0.65,
      "implied_move_pct": 2.3,
      "skew_bias": "bullish"
    },
    "sentiment": {
      "bullish_ratio": 0.68,
      "mention_count": 245,
      "trend": "increasing"
    }
  },
  "reason": "Quant ensemble (65% confidence BUY) confirms smart money accumulation with unusual call volume and rising sentiment",
  "alerts_sent": ["telegram"]
}
```

---

## Setup Instructions

### 1. Install Backend Dependencies

```bash
cd /tmp/trading-dashboard/backend
pip install -r requirements.txt  # Ensure aiofiles, aiohttp are in requirements
pip install python-telegram-bot[asyncio] aiohttp  # Telegram bot + async HTTP
```

### 2. Set Environment Variables

```bash
export TELEGRAM_BOT_TOKEN="8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo"
export TELEGRAM_CHAT_ID="5696824719"  # Your Telegram home chat ID
export REDIS_URL="redis://localhost:6379"  # Optional; falls back to in-memory
export FINNHUB_API_KEY="your-finnhub-key"  # From Finnhub
```

Or add to `~/.hermes/config.yaml`:

```yaml
trading:
  telegram:
    bot_token: "8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo"
    chat_id: "5696824719"
  finnhub_key: "your-key-here"
  redis_url: "redis://localhost:6379"
```

### 3. Start the Backend

```bash
cd /tmp/trading-dashboard/backend
python3 main.py
```

Expected startup logs:
```
2026-05-24 14:30:15 - trading_dashboard - INFO - Dashboard backend initialized successfully
2026-05-24 14:30:15 - trading_dashboard - INFO - Telegram bot initialized
2026-05-24 14:30:16 - trading_dashboard - INFO - Signal engine started
```

### 4. Test Signal Generation

```bash
# In a separate terminal, trigger a signal:
curl http://localhost:8000/api/signals/AAPL

# Expected response:
{
  "id": "uuid",
  "symbol": "AAPL",
  "signal": "buy",
  "confidence": 72,
  "components": {...},
  "reason": "..."
}
```

### 5. Test WebSocket Streaming

```bash
# Connect to real-time signal stream:
wscat -c ws://localhost:8000/api/ws/signals

# Subscribe to symbols:
{
  "action": "subscribe",
  "symbols": ["AAPL", "TSLA", "MSFT"]
}

# Receive signals in real-time:
{
  "id": "...",
  "symbol": "AAPL",
  "signal": "buy",
  "confidence": 75,
  ...
}
```

### 6. Set Up Scheduled Cronjobs

```bash
# Make scripts executable
chmod +x ~/.hermes/scripts/signal-scanner-runner.sh
chmod +x ~/.hermes/scripts/setup-signal-cronjobs.sh

# Install cron jobs (registers pre-market, open, hourly, after-hours scans)
bash ~/.hermes/scripts/setup-signal-cronjobs.sh

# Verify installation
crontab -l | grep signal-scanner

# Logs
tail -f ~/.hermes/logs/signal-scanner.log
```

---

## API Endpoints

### GET /api/signals/
**Latest signals feed**

```bash
curl http://localhost:8000/api/signals/?limit=10&min_confidence=60
```

Response:
```json
{
  "signals": [
    {
      "id": "...",
      "symbol": "AAPL",
      "signal": "buy",
      "confidence": 72,
      "timestamp": "2026-05-24T14:32:15Z",
      ...
    }
  ],
  "total": 42,
  "latest_timestamp": "2026-05-24T14:32:15Z"
}
```

### GET /api/signals/{symbol}
**Latest signal for symbol with component breakdown**

```bash
curl http://localhost:8000/api/signals/AAPL
```

### GET /api/signals/{symbol}/history
**Signal history (24h, 7d, 30d)**

```bash
curl "http://localhost:8000/api/signals/AAPL/history?period=7d&limit=50"
```

### GET /api/scanner/{scanner_type}
**Scanner-specific output (detailed view)**

```bash
curl http://localhost:8000/api/scanner/smart_money?symbol=AAPL&period=30d
```

Scanners:
- `smart_money` - Institutional accumulation, volume patterns
- `options` - Unusual volume, put/call ratios, skew
- `sec` - Form 4/8-K filings, insider activity
- `sentiment` - StockTwits, news, Reddit
- `short_interest` - Short float %, squeeze signals
- `news` - Recent news, earnings dates
- `technical` - MA, RSI, MACD, patterns
- `quant_ensemble` - 7-strategy consensus

### POST /api/telegram/webhook
**Incoming Telegram commands** (e.g., `/status`, `/signals`, `/watchlist`)

---

## Telegram Integration

### Alert Format

```
📊 SIGNAL ALERT
━━━━━━━━━━━━━━━
Symbol: AAPL
Signal: 🚀 BUY (72% confidence)
Price: $150.23
Reason: Quant ensemble + smart money accumulation

📈 Components:
  Quant: 65% (momentum + gap-and-go)
  SmartMoney: 68% (3 insider buys, 82% concentration)
  Options: High unusual call volume
  Sentiment: 68% bullish

⏰ 2026-05-24 14:32:15 UTC
```

### Commands

```
/status           - System health check
/signals          - Recent high-confidence signals
/watchlist        - Current watchlist with latest prices
/scanner {type}   - Detailed scanner output (e.g., /scanner smart_money)
/subscribe AAPL   - Subscribe to symbol alerts
/unsubscribe AAPL - Unsubscribe from symbol
```

---

## Scanner Details

### 1. SmartMoney (Weight: 25%)
Detects institutional accumulation patterns:
- Insider transactions (Form 4)
- Volume concentration analysis
- Unusual positioning (Level 2 order book)
- Position growth trends

**Signal:** BUY if 3+ insider buys in 30d AND position concentration > 70%

### 2. Options (Weight: 20%)
Analyzes options market behavior:
- Unusual call/put volume
- Put/call ratio extremes
- Implied move vs realized
- Skew bias (calls > puts = bullish)

**Signal:** BUY if call volume spike + skew bullish + implied move > expected volatility

### 3. SEC Filing (Weight: 15%)
Monitors SEC filings for catalysts:
- Form 4 (insider trades)
- 8-K (material events)
- 13F (institutional holdings)
- Proxy statements

**Signal:** BUY if CEO/director insider buy + 8-K positive catalyst

### 4. Sentiment (Weight: 15%)
Aggregates social sentiment:
- StockTwits bullish/bearish ratio
- Recent news mentions
- Reddit discussion volume
- Tone analysis (positive/negative)

**Signal:** BUY if bullish ratio > 65% AND mention trend increasing

### 5. Short Interest (Weight: 10%)
Detects short squeeze potential:
- Short float % (>20% = squeeze candidate)
- Borrow fees (>5% = hard to borrow)
- Days-to-cover (>2 = extended)
- Failure-to-deliver patterns

**Signal:** BUY if short float > 25% AND price breaks resistance (forced cover)

### 6. News (Weight: 10%)
Tracks earnings, FDA, regulatory events:
- Earnings announcements
- FDA approval dates
- Regulatory decisions
- Strategic partnerships

**Signal:** BUY if positive catalyst within 5 trading days

### 7. Technical (Weight: 10%)
Classic technical analysis:
- Moving averages (20, 50, 200)
- RSI (overbought/oversold)
- MACD (momentum)
- Support/resistance levels

**Signal:** BUY if price breaks above resistance + RSI < 70 (room to run)

### 8. Quant Ensemble (Weight: 25%)
7-strategy mathematical consensus:
- Momentum (trend following)
- Mean Reversion (contrarian)
- Volatility Regime (adaptive)
- Pattern Recognition (gap-and-go, VWAP)
- Market Regime (bull calm vs bull stressed)
- Correlation Arbitrage (pairs trades)
- Leading Indicators (predictive)

**Signal:** Weighted voting, score -1 to +1, confidence 0-100%

---

## Operational Workflows

### Daily Alert Review

```bash
# Check today's signals
tail -20 ~/.hermes/logs/signal-scanner.log

# Filter by confidence
grep "confidence.*[8-9][0-9]" ~/.hermes/logs/signal-scanner.log

# Count by signal type
grep "signal.*buy" ~/.hermes/logs/signal-scanner.log | wc -l
```

### Adjust Scanner Weights

Edit `/tmp/trading-dashboard/backend/signal_engine.py`:

```python
SCANNER_WEIGHTS = {
    "quant_ensemble": 0.25,      # Change from 0.25
    "smart_money": 0.20,
    "options": 0.15,
    "sentiment": 0.15,
    "short_interest": 0.10,
    "news": 0.10,
    "technical": 0.05,          # Low weight (basic TA)
}
```

### Monitor Real-Time Signals

```bash
# Open dashboard at http://localhost:3000
# Signal feed shows recent alerts with component breakdown

# Or use API:
watch -n 5 'curl -s http://localhost:8000/api/signals/ | jq ".signals[0]"'
```

### Test Scanner Individually

```python
# Test SmartMoney scanner
from scanners.smart_money_scanner import SmartMoneyScanner

scanner = SmartMoneyScanner()
result = await scanner.scan("AAPL", price=150.23, volume=2500000)
print(result)  # {"score": 0.65, "reason": "...", "components": {...}}
```

---

## Troubleshooting

### No Signals Generated

**Symptom:** API returns empty signal list

**Diagnosis:**
1. Check Finnhub API key: `echo $FINNHUB_API_KEY`
2. Test Finnhub connectivity: `curl https://finnhub.io/api/v1/quote?symbol=AAPL&token=$FINNHUB_API_KEY`
3. Check signal engine logs: `tail -20 ~/.hermes/logs/signal-scanner.log | grep error`

**Fix:**
```bash
# Restart backend with debug logging
LOGLEVEL=DEBUG python3 /tmp/trading-dashboard/backend/main.py
```

### Telegram Not Sending Alerts

**Symptom:** Signals generated but no Telegram messages

**Diagnosis:**
1. Verify bot token: `hermes config get trading.telegram.bot_token`
2. Test Telegram API: 
   ```bash
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
     -d "chat_id=${TELEGRAM_CHAT_ID}" \
     -d "text=Test"
   ```
3. Check if chat ID is correct: Use `@JsonDumpBot` in Telegram to confirm ID

**Fix:**
```bash
# Restart Telegram bot
kill $(ps aux | grep telegram_bot | grep -v grep | awk '{print $2}')
python3 /tmp/trading-dashboard/backend/main.py
```

### WebSocket Not Streaming

**Symptom:** WebSocket connects but no signal updates

**Diagnosis:**
1. Check WebSocket endpoint: `curl -i http://localhost:8000/api/ws`
2. Verify signal generation: `curl http://localhost:8000/api/signals/AAPL`

**Fix:**
```bash
# Restart backend
pkill -f "python3 main.py"
cd /tmp/trading-dashboard/backend
python3 main.py
```

### Memory Leak in Signal Engine

**Symptom:** Backend process grows to 1GB+ RAM

**Diagnosis:**
1. Check cache size: `redis-cli INFO memory`
2. Review signal caching logic in `signal_engine.py`

**Fix:**
```bash
# Clear cache and restart
redis-cli FLUSHALL
python3 /tmp/trading-dashboard/backend/main.py
```

---

## Performance Optimization

### Cache TTL Tuning

In `signal_engine.py`:

```python
# Default: 300 seconds (5 min)
CACHE_TTL = 300

# For slower markets: 600 seconds (10 min)
# For faster markets: 120 seconds (2 min)
CACHE_TTL = 600
```

### Parallel Scanner Execution

Controlled by `MAX_CONCURRENT_SCANNERS` in `signal_engine.py`:

```python
# Default: 4 concurrent scanners
# Higher = faster but uses more CPU/memory
# Lower = slower but uses less resources
MAX_CONCURRENT_SCANNERS = 4
```

### Redis vs In-Memory

For production, use Redis (faster, distributed):

```bash
redis-server --daemonize yes
export REDIS_URL="redis://localhost:6379"
python3 main.py
```

For development (in-memory, no setup):

```bash
# Unset REDIS_URL to use fallback
unset REDIS_URL
python3 main.py
```

---

## Deployment to DigitalOcean

Once tested locally, push to GitHub and deploy:

```bash
cd /tmp/trading-dashboard
git add .
git commit -m "Add signal generation pipeline (8 scanners, Telegram bot)"
git push origin main

# Dashboard auto-deploys via app.yaml config
# Check status at https://cloud.digitalocean.com/apps
```

---

## Next Steps

- ✅ Signal generation pipeline complete
- ✅ 8 scanner modules ready
- ✅ Telegram bot configured
- ⏳ **Next**: Dashboard UI updates (signal feed component, scanner details panel)
- ⏳ **Later**: Real data source integration (Finnhub, IBKR, Fintel API)
- ⏳ **Later**: Backtesting framework for signal validation

---

**Last Updated**: 2026-05-24  
**Status**: Production-ready (mocked data)  
**Maintainer**: Schyler McNaly
