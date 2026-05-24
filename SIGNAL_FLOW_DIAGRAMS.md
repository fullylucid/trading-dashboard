# Signal Generation - Data Flow & System Behavior

## Real-Time Signal Generation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     SIGNAL REQUEST                              │
│                  (API or Cronjob Trigger)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │  Signal Engine (main task)   │
              ├──────────────────────────────┤
              │ 1. Fetch OHLCV data          │
              │    (Finnhub API)             │
              └────────────┬─────────────────┘
                           │
              ┌────────────▼────────────┐
              │  Run 8 Scanners         │
              │  (in parallel)          │
              ├────────────┬────────────┤
              │            │            │
    ┌─────────▼──┐ ┌──────▼──┐ ┌──────▼────────┐
    │SmartMoney  │ │ Options │ │SEC + Sentiment│
    │Score: 0.68 │ │Score:.75│ │Score: 0.62    │
    └────────────┘ └─────────┘ └───────────────┘
              │            │            │
    ┌─────────▼──┐ ┌──────▼──┐ ┌──────▼────────┐
    │ShortInt    │ │  News   │ │Technical      │
    │Score: 0.55 │ │Score:.45│ │Score: 0.72    │
    └────────────┘ └─────────┘ └───────────────┘
              │            │            │
         ┌────▼────────────▼────────────▼────┐
         │ QuantEnsemble (7-strategy):        │
         │ - Momentum: +0.8                   │
         │ - Mean-reversion: -0.3             │
         │ - Volatility regime: NORMAL        │
         │ - Pattern: gap-and-go              │
         │ Final score: 0.65                  │
         └────────────────┬────────────────────┘
                          │
              ┌───────────▼──────────────┐
              │ Weighted Aggregation      │
              ├───────────────────────────┤
              │ SmartMoney (25%): 0.68    │
              │ Options (20%):    0.75    │
              │ SEC (15%):        0.62    │
              │ Sentiment (15%):  0.62    │
              │ ShortInt (10%):   0.55    │
              │ News (10%):       0.45    │
              │ Technical (10%):  0.72    │
              │ QuantEnsemble(25%): 0.65  │
              │ ─────────────────────────  │
              │ Final: 0.64 → 64%         │
              └───────────┬────────────────┘
                          │
                          ▼
            ┌─────────────────────────┐
            │  Generate Signal Object │
            ├─────────────────────────┤
            │ ✓ ID + timestamp        │
            │ ✓ Symbol + price        │
            │ ✓ Signal: BUY           │
            │ ✓ Confidence: 64%       │
            │ ✓ Components breakdown  │
            │ ✓ Reason text           │
            └──────────┬──────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   ┌─────────┐  ┌──────────┐  ┌─────────────┐
   │ Redis   │  │ WebSocket│  │  Telegram   │
   │ Cache   │  │Broadcast │  │ Message Q   │
   │(5 min)  │  │to clients│  │(async send) │
   └─────────┘  └──────────┘  └─────────────┘
        │              │              │
        └──────────────┼──────────────┘
                       │
                       ▼
          ┌────────────────────────────┐
          │   SIGNAL DELIVERED         │
          ├────────────────────────────┤
          │ • Dashboard (WebSocket)    │
          │ • API response (REST)      │
          │ • Telegram alert (async)   │
          │ • Logs (analytics.jsonl)   │
          └────────────────────────────┘
```

---

## Component Breakdown Visualization

When user clicks "AAPL" signal on dashboard:

```
SIGNAL ALERT: AAPL - BUY (64% confidence)
═════════════════════════════════════════════

📊 QUANT ENSEMBLE (25% weight, score: 65%)
   ├─ Momentum:        +0.80 (strong bullish)
   ├─ Mean-reversion:  -0.30 (slight bearish)
   ├─ Volatility:      NORMAL
   ├─ Pattern:         gap-and-go
   ├─ Regime:          bull calm
   └─ Final:           65% confidence
   
💰 SMART MONEY (25% weight, score: 68%)
   ├─ Insider buys (30d): 3
   ├─ Position concentration: 82%
   ├─ Volume ratio: 1.45x
   └─ Confidence:    68% (ACCUMULATING)

📈 OPTIONS (20% weight, score: 75%)
   ├─ Unusual call volume: YES
   ├─ Put/call ratio: 0.65 (bullish)
   ├─ Implied move: 2.3%
   ├─ Skew bias: BULLISH
   └─ Confidence:    75% (BULLISH)

🔐 SEC FILINGS (15% weight, score: 62%)
   ├─ Form 4 (insider buys): CEO, CTO
   ├─ 8-K (recent): None
   ├─ Days since last buy: 2 days
   └─ Confidence:    62% (RECENT BUYING)

💬 SENTIMENT (15% weight, score: 62%)
   ├─ StockTwits bullish: 68%
   ├─ Recent mentions: 245
   ├─ Trend: INCREASING
   └─ Confidence:    62% (BULLISH SHIFT)

📉 SHORT INTEREST (10% weight, score: 55%)
   ├─ Short float: 18%
   ├─ Days-to-cover: 1.8
   ├─ Borrow fee: 2.3%
   └─ Confidence:    55% (NORMAL)

📰 NEWS (10% weight, score: 45%)
   ├─ Recent news: 2 positive
   ├─ Next earnings: 22 days
   ├─ Catalysts: None imminent
   └─ Confidence:    45% (NEUTRAL)

📊 TECHNICAL (10% weight, score: 72%)
   ├─ MA(20) cross above MA(50): YES
   ├─ RSI(14): 62 (neutral)
   ├─ MACD: BULLISH crossover
   ├─ Support: $147.50 (strong)
   └─ Confidence:    72% (BULLISH)

═════════════════════════════════════════════
FINAL SCORE: 64% confidence - BUY
═════════════════════════════════════════════

REASON:
"Quant ensemble detects gap-and-go pattern with bullish MACD,
 confirmed by smart money accumulation (3 insider buys in 30d),
 unusual call volume, and recent SEC Form 4 filings. Technical
 shows MA crossover. Short interest normal but not squeeze signal.
 Risk: News cycle is quiet (execution risk)."

NEXT WATCH POINTS:
✓ Price holds $147.50 support
✓ Volume stays elevated
✓ Short interest rises (squeeze potential)
✓ Next earnings 2026-06-14
```

---

## WebSocket Real-Time Example

**Client subscribes:**
```json
{
  "action": "subscribe",
  "symbols": ["AAPL", "TSLA", "MSFT"]
}
```

**Server responds with live signals as they arrive:**
```json
{
  "timestamp": "2026-05-24T14:32:15Z",
  "symbol": "AAPL",
  "signal": "buy",
  "confidence": 64,
  "price": 150.23,
  "change": "+2.3%",
  "components_summary": {
    "best": "Technical (72%), Options (75%)",
    "weakest": "News (45%)",
    "consensus": "BUY"
  }
}

{
  "timestamp": "2026-05-24T14:35:42Z",
  "symbol": "TSLA",
  "signal": "hold",
  "confidence": 51,
  "price": 248.95,
  ...
}
```

---

## Cronjob Signal Generation

**Timeline (Eastern Time):**

```
6:30 AM → PRE-MARKET SCAN
         ├─ Fetch futures data
         ├─ Check overnight news
         ├─ Run 8 scanners
         ├─ Generate signals for high-conviction only (70%+)
         └─ Telegram alert to home chat

9:30 AM → MARKET OPEN SCAN
         ├─ Market just opened
         ├─ Fresh price data
         ├─ Run full 8 scanners
         ├─ Generate all signals (50%+)
         └─ Telegram alert with top 3 signals

10 AM - 3 PM → HOURLY SCANS (every hour)
         ├─ Run quick scan
         ├─ Alert only if confidence > 70%
         └─ Telegram for high-conviction only

4:15 PM → AFTER-HOURS SCAN
         ├─ Market just closed
         ├─ Run final 8 scanners
         ├─ Overnight positioning
         └─ Telegram summary + watchlist

All times ET (user sees PT conversion)
```

---

## Signal Confidence Examples

```
HIGH CONFIDENCE (70-100%)
  "Strong quant consensus (75%) + insider buying + unusual volume"
  → BUY at $150.23 (72% confidence)

MEDIUM CONFIDENCE (50-70%)
  "Technical crossover + sentiment improving"
  → BUY at $45.67 (58% confidence)

LOW CONFIDENCE (0-50%)
  "One scanner bullish, others neutral/bearish"
  → HOLD at $87.34 (42% confidence)

REJECT SIGNAL (<30%)
  "Not generated - confidence below threshold"
  → Not sent to dashboard
```

---

## Error Handling & Resilience

```
Signal Generation → Error? → Circuit Breaker
                        │
                    Scanner timeout?
                    ├─ Retry 3x (exponential backoff)
                    ├─ If still fails: skip scanner, proceed with others
                    └─ Log failure for monitoring
                    
Telegram delivery → Error?
                    ├─ Retry 5x (exponential backoff)
                    ├─ If still fails: log, alert operator
                    └─ Store in queue for manual retry

Cache miss?
    ├─ Fall back to live computation
    └─ Repopulate cache on success

API endpoint down?
    ├─ Return cached signal (if available)
    └─ Mark as stale: "cached, 5 min old"
```

---

## Performance Expectations

```
BEST CASE (all systems optimal):
- Signal generated: 800ms
- WebSocket delivery: 10ms
- Telegram: 500ms
- Total: 1.3 seconds ⚡

TYPICAL CASE:
- Signal generated: 1.5s
- WebSocket delivery: 50ms
- Telegram: 2s
- Total: 3.5 seconds ✓

DEGRADED (1 scanner slow):
- Signal generated: 2.5s (timeout + others continue)
- WebSocket delivery: 100ms
- Telegram: 3s
- Total: 5.6 seconds ⚠️

EDGE CASE (API down):
- Signal generated: 5s (circuit break, use cache)
- WebSocket delivery: 200ms
- Telegram: 10s (retry logic)
- Total: 15+ seconds (alert sent, stale data noted)
```

---

**SIGNAL SYSTEM READY FOR PRODUCTION**

All flows tested and documented. ✓
