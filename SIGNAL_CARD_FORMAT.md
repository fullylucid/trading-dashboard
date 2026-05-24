# Signal Card Format Specification

## Format: Enhanced OpenClaw Design + Improvements

Updated signal cards now match and exceed the OpenClaw format with the following structure:

---

## Telegram Message Format Example

```
🔍 DISCOVERY
$MU • Micron Technology, Inc.

🏢 Semiconductors | United States
💰 Market Cap: $842.2B

💎 Edge: Pioneering HBM3E memory for AI GPUs with 50% faster data throughput

📊 Signal Score: 70/100 [███████░░]
📈 Price: $746.81 (+15.5%)
📊 Volume: 1.6x avg

🎯 Catalyst: 50-day new high + volume surge
   ⚪ 50-day new high
   ⚪ Gap +4.6%
   ⚪ ATR breakout (1.5σ above MA20)

🎯 Entry: $746.81
🛑 Stop: $710.47
🚀 Target: $820.48
📊 Risk/Reward: 1:1.9

💡 Position Size: 2-3%

🔬 Signal Breakdown:
   Quant Ensemble: 75% [███████░░]
   Smart Money: 68% [██████░░░]
   Options: 75% [███████░░]
   Sec: 62% [██████░░░░]
   Sentiment: 62% [██████░░░░]
   Short Interest: 55% [█████░░░░░]
   News: 45% [████░░░░░░]
   Technical: 72% [███████░░░]

✅ Action: MONITOR
   Confirmation: Price holds above $740, volume sustains
   
⏰ 5:12 PM
```

---

## Data Hierarchy (Same as OpenClaw)

```
PRIORITY 1 (Highest Impact)
├─ Signal Type (DISCOVERY, MOMENTUM, REVERSAL, SQUEEZE)
├─ Ticker Symbol ($MU)
└─ Company Name

PRIORITY 2 (Key Context)
├─ Industry
├─ Market Cap
└─ Competitive Edge (why this matters)

PRIORITY 3 (Scoring)
├─ Signal Score (0-100%)
└─ Visual score bar [████░]

PRIORITY 4 (Market Data)
├─ Price
├─ % Change
└─ Volume

PRIORITY 5 (Timing)
├─ Primary Catalyst
└─ Supporting Signals

PRIORITY 6 (Risk/Reward) ✨ NEW
├─ Entry Price
├─ Stop Loss
├─ Target Price
└─ Risk/Reward Ratio (1:X)

PRIORITY 7 (Component Breakdown) ✨ NEW
├─ All 8 scanner scores
└─ Visual confidence bars

PRIORITY 8 (Action)
├─ BUY/MONITOR/WAIT
└─ Confirmation Criteria ✨ IMPROVED

PRIORITY 9 (Metadata)
├─ Position Size ✨ NEW
└─ Timestamp
```

---

## Emoji System (Semantic Color Coding)

```
SIGNAL TYPES & CATEGORIES
🔍 Discovery          → New discovery
📊 Momentum          → Strong directional move
📉 Reversal          → Trend reversal detected
🎯 Squeeze           → Short squeeze signal
⚡ Breakout          → Resistance breakthrough

COMPANY & CONTEXT
🏢 Industry          → Industry classification
💎 Edge             → Competitive advantage
🌍 Location         → Country

SCORING & METRICS
📊 Score            → Signal confidence
📈 Price            → Current price level
📊 Volume           → Trading volume
💰 Market Cap       → Company valuation

CATALYSTS & TRIGGERS
🎯 Catalyst         → Primary reason
⚪ Other signals    → Supporting signals
📅 Catalyst date    → Days to event

RISK/REWARD
🎯 Entry            → Entry price
🛑 Stop Loss        → Stop loss level
🚀 Target           → Price target
📊 Risk/Reward      → R:R ratio

COMPONENTS
🔬 Breakdown        → Scanner details
📊 Scanner name     → Individual scores

ACTIONS
✅ Buy/Monitor      → Action button
💡 Confirmation     → Entry criteria
📍 Position Size    → Sizing guidance

TIME
⏰ Timestamp        → When signal was generated
📅 Days to catalyst → Time until event
```

---

## HTML Card Component (For Dashboard)

The same signal generates an HTML card for the React dashboard:

```html
<div class="signal-card" style="border-left: 4px solid #00aa00;">
    <div class="card-header">
        <div class="signal-type">🔍 DISCOVERY</div>
        <div class="ticker" style="color: #0066cc;">$MU</div>
        <div class="company">Micron Technology, Inc.</div>
    </div>
    
    <div class="card-body">
        <div class="company-info">
            🏢 Semiconductors | United States | 💰 $842.2B
        </div>
        
        <div class="edge">
            <strong>💎 Edge:</strong> Pioneering HBM3E memory for AI GPUs 
                                      with 50% faster data throughput
        </div>
        
        <div class="metrics">
            <div class="metric">
                <span>📊 Score: <strong>70/100</strong></span>
                <div class="score-bar">
                    <div class="score-fill" 
                         style="width: 70%; background: #ffaa00;"></div>
                </div>
            </div>
            <div class="metric">
                <span>💰 Price: <strong>$746.81</strong></span>
                <span style="color: green;">(+15.5%)</span>
            </div>
            <div class="metric">
                <span>📈 Volume: <strong>1.6x avg</strong></span>
            </div>
        </div>
        
        <div class="catalyst">
            <strong>🎯 Catalyst:</strong> 50-day new high + volume surge
            <ul>
                <li>⚪ 50-day new high</li>
                <li>⚪ Gap +4.6%</li>
                <li>⚪ ATR breakout (1.5σ above MA20)</li>
            </ul>
        </div>
        
        <div class="risk-reward">
            <div class="rr-item">Entry: $746.81</div>
            <div class="rr-item">Stop: $710.47</div>
            <div class="rr-item">Target: $820.48</div>
            <div class="rr-item"><strong>Risk/Reward: 1:1.9</strong></div>
        </div>
        
        <div class="components">
            <strong>🔬 Signal Components:</strong>
            <div class='components-list'>
                <div class='component'>
                    <span>Quant Ensemble: 75%</span>
                    <span>[███████░░]</span>
                </div>
                <div class='component'>
                    <span>Smart Money: 68%</span>
                    <span>[██████░░░]</span>
                </div>
                <!-- 6 more scanners... -->
            </div>
        </div>
        
        <div class="action">
            <strong>💡 Action: MONITOR</strong>
            <div>Confirmation: Price holds above $740, volume sustains</div>
            <div>Position: 2-3%</div>
        </div>
    </div>
    
    <div class="card-footer">
        5:12 PM
    </div>
</div>
```

---

## Key Improvements Over OpenClaw

| Feature | OpenClaw | Updated | Benefit |
|---------|----------|---------|---------|
| Signal Score | ✓ | ✓ + Bar | Visual confidence at glance |
| Component Breakdown | ✗ | ✓ | See which scanners agree |
| Entry Price | ✗ | ✓ | Exact entry level |
| Stop Loss | ✗ | ✓ | Risk management |
| Target Price | ✗ | ✓ | Profit objective |
| Risk/Reward | ✗ | ✓ 1:1.9 | Position sizing math |
| Position Size | ✗ | ✓ 2-3% | Account management |
| Confirmation Criteria | Vague | Specific | Exact entry trigger |
| Catalyst Days | ✗ | ✓ | Time-sensitive context |
| Mobile Responsive | ✓ | ✓ | Same design |
| Emojis | ✓ | ✓ | Enhanced clarity |
| HTML Cards | ✗ | ✓ | Dashboard integration |

---

## Usage in Different Channels

### 1. Telegram (HTML)
- Uses HTML formatting with <b>, <code>, line breaks
- Emojis rendered as images
- Score bars using Unicode (█░)
- Clickable links for tickers

### 2. WebSocket (JSON)
- Sends raw signal object
- Includes pre-formatted telegram message
- Dashboard renders as HTML card
- Real-time updates

### 3. REST API (/api/signals/{symbol})
- Returns full JSON object
- Includes both telegram and HTML formats
- Components breakdown available
- Historical performance included

### 4. Dashboard (React)
- Renders HTML card with CSS styling
- Interactive: click to expand components
- Real-time updates via WebSocket
- Sortable/filterable signal feed

---

## Code Integration

```python
from signal_formatter import SignalCard, SignalFormatterUtil

# Create signal card from scanner data
signal_card = SignalFormatterUtil.create_signal_card(
    signal_data={"symbol": "MU", "confidence": 70, "signal_type": "DISCOVERY"},
    company_data={"name": "Micron Technology", "edge": "HBM3E memory..."},
    market_data={"price": 746.81, "price_change_pct": 15.5, "volume_ratio": 1.6},
    analysis_data={
        "catalyst": "50-day new high + volume surge",
        "other_signals": ["50-day new high", "Gap +4.6%", "ATR breakout"],
        "entry_price": 746.81,
        "stop_loss": 710.47,
        "target_price": 820.48,
        "components": {
            "quant_ensemble": 0.75,
            "smart_money": 0.68,
            # ... all 8 scanners
        }
    }
)

# Send via Telegram
telegram_message = signal_card.to_telegram()
await telegram_bot.send_message(chat_id, telegram_message)

# Send via WebSocket
json_payload = signal_card.to_dict()
await websocket.broadcast(json_payload)

# Render on dashboard
html_card = signal_card.to_html_card()
```

---

## Configuration

Adjustable settings in `signal_formatter.py`:

```python
# Score color thresholds
SCORE_GREEN = 75    # >= 75% = green
SCORE_ORANGE = 60   # >= 60% = orange
SCORE_YELLOW = 50   # >= 50% = yellow
SCORE_RED = 0       # < 50% = red

# Action thresholds
BUY_THRESHOLD = 70       # >= 70% = BUY
MONITOR_THRESHOLD = 60   # >= 60% = MONITOR
WAIT_THRESHOLD = 50      # < 50% = WAIT

# Signal categories
SIGNAL_TYPES = ["DISCOVERY", "MOMENTUM", "REVERSAL", "SQUEEZE", "BREAKOUT"]

# Default position sizing
DEFAULT_POSITION_SIZE = "2-3%"  # Per risk level
```

---

## Testing the Format

```bash
# Test locally
python3 -c "
from signal_formatter import SignalCard, SignalFormatterUtil
from datetime import datetime

card = SignalCard(
    symbol='MU',
    company_name='Micron Technology',
    signal_type='DISCOVERY',
    industry='Semiconductors',
    country='United States',
    market_cap='\$842.2B',
    edge='Pioneering HBM3E memory for AI GPUs',
    score=70,
    sector='Tech',
    price=746.81,
    price_change_pct=15.5,
    volume_ratio=1.6,
    primary_catalyst='50-day new high + volume surge',
    other_signals=['50-day new high', 'Gap +4.6%', 'ATR breakout'],
    entry_price=746.81,
    stop_loss=710.47,
    target_price=820.48,
    risk_reward_ratio=1.9,
    action='MONITOR',
    confirmation_criteria='Price holds above $740, volume sustains',
    position_size='2-3%',
    timestamp=datetime.now(),
    signal_confidence={
        'quant_ensemble': 0.75,
        'smart_money': 0.68,
        'options': 0.75,
        'sec': 0.62,
        'sentiment': 0.62,
        'short_interest': 0.55,
        'news': 0.45,
        'technical': 0.72,
    }
)

print(card.to_telegram())
"
```

---

## Format Timeline

- **OpenClaw Format**: Reference baseline (good)
- **Updated Format**: Enhanced with risk/reward, components, specific confirmation
- **Future**: AI-generated card descriptions, performance tracking, backtest results

---

**Status**: ✅ Format specification complete and integrated into signal_formatter.py

All signals will be displayed in this enhanced format across:
- Telegram (HTML-formatted messages)
- WebSocket (JSON with pre-formatted message)
- REST API (complete JSON object)
- Dashboard (rendered HTML card)
