# 🤖 Signal Bot Integration - Daily Telegram Delivery

## Setup

You mentioned providing a dedicated signal bot token for daily signal delivery. Here's how to integrate it:

### Step 1: Add Bot Token to Environment

Create/update `.env` in your dashboard:

```bash
# Signal Bot Token
SIGNAL_BOT_TOKEN=your_bot_token_here
SIGNAL_BOT_CHAT_ID=your_chat_id_here
OLLAMA_CLOUD_URL=https://api.ollama.cloud
```

### Step 2: Create Scheduled Signal Delivery Cron

File: `backend/signal_scheduler.py`

```python
import asyncio
import logging
from datetime import datetime
from aiogram import Bot
from signal_formatter import SignalCard
from signal_engine import SignalEngine

logger = logging.getLogger(__name__)

class SignalScheduler:
    """Scheduled signal delivery via Telegram bot"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.engine = SignalEngine()
    
    async def send_daily_signals(self):
        """Send top signals daily"""
        try:
            # Get top 5 signals
            signals = await self.engine.get_signals(symbols=[], limit=5)
            
            for signal_data in signals:
                card = SignalCard.from_dict(signal_data)
                message = card.to_telegram()
                
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='HTML'
                )
                
                await asyncio.sleep(1)  # Rate limit
            
            logger.info(f"Sent {len(signals)} signals at {datetime.now()}")
            
        except Exception as e:
            logger.error(f"Error sending signals: {e}")
    
    async def send_signal(self, signal_data: dict):
        """Send single signal immediately"""
        try:
            card = SignalCard.from_dict(signal_data)
            message = card.to_telegram()
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error sending signal: {e}")
```

### Step 3: Hermes Cron Integration

Add to your Hermes config or use CLI:

```bash
# Every day at 6:30 AM ET, 9:30 AM ET, and 4:15 PM ET

hermes cronjob create \
  --name="signal-delivery-premarket" \
  --schedule="30 6 * * *" \
  --prompt="Run daily pre-market signal scan and deliver to Telegram bot" \
  --script="~/.hermes/scripts/signal_daily.py"
```

Create script: `~/.hermes/scripts/signal_daily.py`

```python
#!/usr/bin/env python3
"""Daily signal delivery script"""

import asyncio
import os
from backend.signal_scheduler import SignalScheduler

async def main():
    bot_token = os.getenv("SIGNAL_BOT_TOKEN")
    chat_id = os.getenv("SIGNAL_BOT_CHAT_ID")
    
    scheduler = SignalScheduler(bot_token, chat_id)
    await scheduler.send_daily_signals()

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 4: Alternative - FastAPI Endpoint

Or add endpoint to trigger signals on-demand:

```python
@app.post("/api/signals/deliver")
async def deliver_signals(limit: int = 5):
    """Deliver signals to Telegram bot"""
    scheduler = SignalScheduler(
        os.getenv("SIGNAL_BOT_TOKEN"),
        os.getenv("SIGNAL_BOT_CHAT_ID")
    )
    await scheduler.send_daily_signals()
    return {"status": "sent"}
```

## Daily Delivery Schedule

```
┌─────────────────────────────────────────────────┐
│             SIGNAL DELIVERY SCHEDULE             │
├─────────────────────────────────────────────────┤
│ 6:30 AM ET  → Pre-market scan (earnings, gaps)  │
│ 9:30 AM ET  → Market open scan (momentum)       │
│ Hourly      → Live signal updates (10 AM-3 PM)  │
│ 4:15 PM ET  → Post-market analysis              │
└─────────────────────────────────────────────────┘
```

## Signal Card Format (Telegram)

Each signal delivers as:

```
🔍 DISCOVERY - $MU
━━━━━━━━━━━━━━━━━━
📊 Score: 73/100

💡 Edge
Smart money accumulation on breakout

🎯 Entry: $746.81
🛑 Stop: $710.00
🚀 Target: $820.00
Risk/Reward: 1:1.0

📈 Recent Action
Volume surge 50% above average
50-day breakout confirmed

📰 Related News (3 articles)
• AAPL Supplier Reports Strong Q4
• Semiconductor Shortage Easing

🔧 Scanner Breakdown
SmartMoney: ████████░░ 0.25 (25%)
Options: ███████░░░ 0.20 (20%)
SEC: ██████░░░░ 0.15 (15%)
Sentiment: ██████░░░░ 0.15 (15%)
ShortInt: █████░░░░░ 0.10 (10%)
News: █████░░░░░ 0.10 (10%)
Technical: █████░░░░░ 0.10 (10%)
QuantEnsemble: 0.65 (composite)

⏰ 2024-01-15 10:23 AM ET
```

## Bot Features

**Immediate Delivery:**
- POST /api/signals/deliver → Sends top 5 signals now

**Scheduled Delivery:**
- Daily at 6:30 AM (pre-market)
- Daily at 9:30 AM (market open)
- Hourly 10 AM-3 PM (intraday)
- Daily at 4:15 PM (after-hours)

**Interactive:**
- User can request `/signals AAPL` in chat
- Bot responds with AAPL-specific signals
- Click reactions to set alerts

## Configuration Files

### .env Template

```bash
# Dashboard API
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=8000

# Signal Bot
SIGNAL_BOT_TOKEN=your_telegram_bot_token
SIGNAL_BOT_CHAT_ID=your_chat_id_or_username

# Market Data APIs
FINNHUB_KEY=your_finnhub_api_key
FMP_KEY=your_fmp_api_key
ALPHA_VANTAGE_KEY=your_alpha_vantage_key

# Ollama Cloud (Kimi K)
OLLAMA_CLOUD_URL=https://api.ollama.cloud
OLLAMA_CLOUD_KEY=your_ollama_cloud_key

# Database
DATABASE_URL=sqlite:///./trading_signals.db
```

## Testing

```bash
# Test bot connection
curl -X POST http://localhost:8000/api/signals/deliver

# View signal logs
tail -f ~/.hermes/logs/signals.log

# Manual signal send
python -c "
import asyncio
from backend.signal_scheduler import SignalScheduler
asyncio.run(SignalScheduler('token', 'chat_id').send_daily_signals())
"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No signals sent | Check bot token + chat ID in .env |
| Telegram 429 (rate limit) | Signals are rate-limited to 1 per second |
| Missing API data | Verify Finnhub/FMP keys are valid |
| Kimi K not responding | Check Ollama Cloud URL and network |

## Next Steps

1. Provide bot token when ready
2. I'll add signal_scheduler.py to backend
3. Set up cron jobs for daily delivery
4. Test with demo signals
5. Deploy to production

---

**Status:** Ready to integrate bot token
**Files needed:** Your Telegram bot token + target chat ID
