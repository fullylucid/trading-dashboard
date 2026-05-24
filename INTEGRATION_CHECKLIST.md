# Trading Dashboard Signal System - Integration Checklist

## Pre-Deployment

- [ ] Backend dependencies installed: `pip install aiofiles aiohttp python-telegram-bot[asyncio]`
- [ ] Environment variables set:
  - [ ] `TELEGRAM_BOT_TOKEN=8704320930:AAFf55JwmNjMXgZOznZvHYZmw_F0h2OfExo`
  - [ ] `TELEGRAM_CHAT_ID=5696824719`
  - [ ] `FINNHUB_API_KEY=<your-key>`
  - [ ] `REDIS_URL=redis://localhost:6379` (optional)

## Local Testing

- [ ] Backend starts without errors: `python3 main.py`
- [ ] Logs show: "Telegram bot initialized", "Signal engine started"
- [ ] Health check passes: `curl http://localhost:8000/api/health`
- [ ] API endpoint works: `curl http://localhost:8000/api/signals/AAPL`
- [ ] WebSocket connects: `wscat -c ws://localhost:8000/api/ws/signals`
- [ ] Telegram test message sent: Check home chat for message from bot

## Scanner Verification

- [ ] SmartMoney scanner returns data: `curl http://localhost:8000/api/scanner/smart_money?symbol=AAPL`
- [ ] Options scanner returns data: `curl http://localhost:8000/api/scanner/options?symbol=AAPL`
- [ ] SEC scanner returns data: `curl http://localhost:8000/api/scanner/sec?symbol=AAPL`
- [ ] Sentiment scanner returns data: `curl http://localhost:8000/api/scanner/sentiment?symbol=AAPL`
- [ ] Quant ensemble returns data: `curl http://localhost:8000/api/scanner/quant_ensemble?symbol=AAPL`

## Performance & Load Testing

- [ ] Backend handles 100 concurrent WebSocket connections
- [ ] Signal generation completes in < 2 seconds per symbol
- [ ] Memory usage stable (no leaks after 1 hour runtime)
- [ ] Telegram message queue clears within 5 seconds
- [ ] API response times < 500ms under normal load

## Frontend Integration

- [ ] React dashboard connects to `/api/ws/signals`
- [ ] Signal feed component displays recent alerts
- [ ] Scanner detail panel shows component breakdown
- [ ] Confidence bars render correctly (0-100%)
- [ ] Timestamp formatting matches user timezone (PT)

## Cronjob Setup

- [ ] Scripts made executable: `chmod +x ~/.hermes/scripts/signal-*.sh`
- [ ] Cronjobs registered: `bash ~/.hermes/scripts/setup-signal-cronjobs.sh`
- [ ] Pre-market job runs at 6:30 AM ET / 3:30 AM PT
- [ ] Market open job runs at 9:30 AM ET / 6:30 AM PT
- [ ] Hourly jobs run 10 AM - 3 PM ET / 7 AM - 12 PM PT
- [ ] After-hours job runs at 4:15 PM ET / 1:15 PM PT
- [ ] Logs visible: `tail -f ~/.hermes/logs/signal-scanner.log`

## DigitalOcean Deployment

- [ ] Code pushed to GitHub: `git push origin main`
- [ ] `app.yaml` present in repo root
- [ ] Environment variables set in DO App Platform dashboard:
  - [ ] `TELEGRAM_BOT_TOKEN`
  - [ ] `TELEGRAM_CHAT_ID`
  - [ ] `FINNHUB_API_KEY`
  - [ ] `REDIS_URL` (if using managed Redis)
- [ ] Backend service builds successfully
- [ ] Dashboard accessible at: `https://trading-dashboard-xxxxx.ondigitalocean.app`
- [ ] Telegram alerts working in production

## Monitoring & Operations

- [ ] Signal analytics logged to: `/tmp/trading-dashboard/logs/signals.jsonl`
- [ ] Backend logs rotated weekly
- [ ] Telegram bot uptime monitored (gateway must stay running)
- [ ] Alert history queryable: `GET /api/signals/{symbol}/history`
- [ ] Scanner health check endpoint: `GET /api/health/scanners`
- [ ] Confidence distribution tracked (for threshold tuning)

## Real Data Integration (Future)

- [ ] [ ] Finnhub API integrated for live price data
- [ ] [ ] IB (Interactive Brokers) connected for smart money
- [ ] [ ] Fintel API integrated for insider trades
- [ ] [ ] StockTwits sentiment API connected
- [ ] [ ] SEC EDGAR parsing for Form 4/8-K
- [ ] [ ] Options market data feed (IVolatility or similar)

## Documentation

- [ ] Setup guide complete: `/tmp/trading-dashboard/SIGNAL_SYSTEM_SETUP.md`
- [ ] Quick start available: `/tmp/trading-dashboard/QUICK_START_SIGNALS.sh`
- [ ] Scanner details documented
- [ ] API endpoint reference complete
- [ ] Troubleshooting guide includes common issues

## Rollback Plan

- [ ] Previous backend version saved/tagged in Git
- [ ] Cronjobs can be disabled: `hermes cronjob pause <job_id>`
- [ ] Telegram bot can be silenced: Set `TELEGRAM_BOT_TOKEN=""` env var
- [ ] Signal engine can be disabled: Comment out in `main.py` startup

---

## Completion Status

**Phase 1 (Completed):**
- ✅ 8-scanner signal generation engine
- ✅ Signal model with component breakdown
- ✅ API endpoints (signals, scanner details, history)
- ✅ WebSocket real-time streaming
- ✅ Telegram bot integration + async message queue
- ✅ Scheduled cronjob infrastructure
- ✅ Error handling + circuit breakers
- ✅ Comprehensive documentation

**Phase 2 (Next Steps):**
- ⏳ React dashboard UI updates (signal feed component)
- ⏳ Scanner detail panel (click to expand)
- ⏳ Live price updates integration
- ⏳ Real data sources (Finnhub, Fintel, SEC EDGAR)

**Phase 3 (Future):**
- ⏳ Backtesting framework for signal validation
- ⏳ Machine learning model for signal confidence
- ⏳ Multi-symbol watchlist optimization
- ⏳ Portfolio risk overlay

---

## Quick Command Reference

```bash
# Start backend
cd /tmp/trading-dashboard/backend && python3 main.py

# Test endpoints
curl http://localhost:8000/api/signals/AAPL
curl http://localhost:8000/api/scanner/smart_money?symbol=AAPL
curl http://localhost:8000/api/signals/AAPL/history?period=7d

# WebSocket
wscat -c ws://localhost:8000/api/ws/signals

# Monitor cronjobs
tail -f ~/.hermes/logs/signal-scanner.log

# Check signal analytics
jq . ~/.hermes/logs/signals.jsonl | head -20

# Deploy to GitHub
git add . && git commit -m "Add signal system" && git push origin main

# View DO dashboard
open https://cloud.digitalocean.com/apps
```

---

**Status**: Ready for deployment  
**Last Updated**: 2026-05-24  
**Owner**: Schyler McNaly
