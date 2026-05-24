# Trading Dashboard - Complete System Architecture

## Overview

Full-stack trading dashboard with **real-time signal generation** from 8 specialized scanners, live price charts, and quantitative analysis.

**Stack:**
- **Frontend**: React 18 (TypeScript, TradingView Lightweight Charts)
- **Backend**: FastAPI (Python 3.10+, async/await)
- **Real-time**: WebSocket streaming + Telegram bot
- **Data**: Finnhub (live prices), Redis (cache)
- **Deployment**: DigitalOcean App Platform ($15/mo)

---

## Core Components

### 1. Signal Engine
- 8 parallel scanners with weighted aggregation
- Confidence scoring (0-100%)
- Component breakdown for transparency
- Circuit breaker fault tolerance
- Redis caching

### 2. Eight Specialized Scanners
- SmartMoney (institutional patterns)
- Options (volume, delta, skew)
- SEC (Form 4, 8-K filings)
- Sentiment (social signals)
- ShortInterest (squeeze detection)
- News (catalysts, earnings)
- Technical (MA, RSI, MACD)
- QuantEnsemble (7-strategy consensus)

### 3. API Layer
- REST endpoints (signals, scanner details, history)
- WebSocket real-time streaming
- Telegram webhook integration

### 4. Data Sources
- Finnhub (live prices)
- Redis (cache, optional)
- Cache Manager (fallback to memory)

### 5. Notification System
- Telegram bot async client
- Message queue + retry logic
- Formatted alerts with confidence

---

## Key Files

**Backend**:
- `main.py` - Application root
- `signal_engine.py` - Orchestrator (11 KB)
- `signal_routes.py` - API endpoints (9.2 KB)
- `websocket_manager.py` - Streaming (9.5 KB)
- `telegram_bot.py` - Bot client (11 KB)
- `scanners/` - 8 scanner modules (40 KB total)

**Frontend**:
- React dashboard with TradingView charts
- WebSocket client for real-time updates
- Signal feed component
- Scanner detail panel

**Docs**:
- `SIGNAL_SYSTEM_SETUP.md` - Complete setup guide
- `INTEGRATION_CHECKLIST.md` - Pre-deployment checklist
- `QUICK_START_SIGNALS.sh` - Quick setup

---

## Signal Model

```json
{
  "id": "uuid",
  "timestamp": "ISO-8601",
  "symbol": "AAPL",
  "signal": "buy|sell|hold",
  "confidence": 0-100,
  "components": {
    "quant_ensemble": {...},
    "smart_money": {...},
    "options": {...}
  },
  "reason": "Human explanation",
  "alerts_sent": ["telegram"]
}
```

---

## Performance

- Signal generation: < 2 seconds
- WebSocket delivery: < 100ms
- API response: < 500ms
- Concurrent clients: 500+

---

**Status**: Production-ready (May 24, 2026)  
**Owner**: Schyler McNaly
