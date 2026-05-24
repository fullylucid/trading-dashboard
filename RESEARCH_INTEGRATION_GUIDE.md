# 🔗 Research System Integration Guide

## Quick Start

### Step 1: Update main.py with Research Routes

Add to `/tmp/trading-dashboard/backend/main.py`:

```python
# Import research components
from research_routes import create_research_routes
from news_aggregator import get_news_aggregator, close_news_aggregator
from earnings_calendar import get_earnings_calendar, close_earnings_calendar
from market_data import get_market_data, close_market_data
from research_agent import get_research_agent, close_research_agent

# Load API keys from environment
import os
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
FMP_KEY = os.getenv("FMP_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

# Initialize research components on startup
@app.on_event("startup")
async def startup_research():
    global news_agg, earnings_cal, market_data_obj, research_agent_obj
    
    news_agg = await get_news_aggregator(ALPHA_VANTAGE_KEY, FINNHUB_KEY)
    earnings_cal = await get_earnings_calendar(FMP_KEY)
    market_data_obj = await get_market_data(FINNHUB_KEY, FMP_KEY)
    research_agent_obj = await get_research_agent()

@app.on_event("shutdown")
async def shutdown_research():
    await close_news_aggregator()
    await close_earnings_calendar()
    await close_market_data()
    await close_research_agent()

# Register research routes
research_router = create_research_routes(
    news_agg=news_agg,
    earnings_cal=earnings_cal,
    market_data=market_data_obj,
    research_agent=research_agent_obj
)
app.include_router(research_router)
```

### Step 2: Update Environment Variables

Add to `.env` or Docker environment:

```bash
# API Keys
FINNHUB_KEY=your_finnhub_key_here
FMP_KEY=your_fmp_key_here
ALPHA_VANTAGE_KEY=your_alpha_vantage_key_here
OLLAMA_CLOUD_URL=https://api.ollama.cloud
```

### Step 3: Test Research Endpoints

```bash
# Test news endpoint
curl http://localhost:8000/api/research/news/AAPL

# Test earnings endpoint
curl http://localhost:8000/api/research/earnings/calendar

# Test market data endpoint
curl http://localhost:8000/api/research/market/summary

# Test research analysis
curl -X POST http://localhost:8000/api/research/analyze/AAPL
```

---

## Frontend Components

### Market Overview Panel

```jsx
import { useEffect, useState } from 'react';

function MarketOverview() {
    const [overview, setOverview] = useState(null);
    
    useEffect(() => {
        fetch('/api/research/market/overview')
            .then(r => r.json())
            .then(data => setOverview(data));
    }, []);
    
    if (!overview) return <div>Loading market data...</div>;
    
    return (
        <div className="market-overview">
            <h2>Market Overview</h2>
            {Object.entries(overview.indices || {}).map(([symbol, data]) => (
                <div key={symbol} className="index-card">
                    <div className="symbol">{data.symbol}</div>
                    <div className="price">${data.price?.toFixed(2)}</div>
                    <div className={`change ${data.change_percent >= 0 ? 'positive' : 'negative'}`}>
                        {data.change_percent >= 0 ? '+' : ''}{data.change_percent?.toFixed(2)}%
                    </div>
                </div>
            ))}
        </div>
    );
}
```

### News Feed Component

```jsx
function NewsFeed({ symbol }) {
    const [news, setNews] = useState([]);
    
    useEffect(() => {
        if (symbol) {
            fetch(`/api/research/news/${symbol}?limit=10`)
                .then(r => r.json())
                .then(data => setNews(data.articles || []));
        }
    }, [symbol]);
    
    return (
        <div className="news-feed">
            <h3>News for {symbol}</h3>
            {news.map((article, i) => (
                <div key={i} className={`news-article sentiment-${article.sentiment}`}>
                    {article.image && <img src={article.image} alt={article.title} />}
                    <div className="content">
                        <h4>{article.title}</h4>
                        <p>{article.summary}</p>
                        <div className="meta">
                            <span className="source">{article.source}</span>
                            <span className="sentiment">{article.sentiment}</span>
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}
```

### Earnings Calendar Component

```jsx
function EarningsCalendar() {
    const [earnings, setEarnings] = useState([]);
    
    useEffect(() => {
        fetch('/api/research/earnings/calendar?days=90&limit=50')
            .then(r => r.json())
            .then(data => setEarnings(data.earnings || []));
    }, []);
    
    return (
        <div className="earnings-calendar">
            <h2>Earnings Calendar</h2>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Date</th>
                        <th>EPS Est.</th>
                        <th>Revenue Est.</th>
                        <th>Sector</th>
                    </tr>
                </thead>
                <tbody>
                    {earnings.map((e, i) => (
                        <tr key={i}>
                            <td className="symbol">{e.symbol}</td>
                            <td>{e.date}</td>
                            <td>${e.eps_estimate?.toFixed(2)}</td>
                            <td>${e.revenue_estimate?.toFixed(1)}B</td>
                            <td>{e.sector}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
```

### Sector Performance Component

```jsx
function SectorPerformance() {
    const [sectors, setSectors] = useState({});
    
    useEffect(() => {
        fetch('/api/research/market/sectors')
            .then(r => r.json())
            .then(data => setSectors(data.sectors || {}));
    }, []);
    
    return (
        <div className="sector-performance">
            <h2>Sector Performance</h2>
            <div className="sector-grid">
                {Object.entries(sectors).map(([name, data]) => (
                    <div key={name} className={`sector-card ${data.performance}`}>
                        <div className="name">{name}</div>
                        <div className="change">{data.change_percent?.toFixed(2)}%</div>
                    </div>
                ))}
            </div>
        </div>
    );
}
```

---

## Dashboard Layout

Suggested layout for enhanced dashboard:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Trading Dashboard                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │  Market Overview     │  │  Sector Perf         │            │
│  │  SPY, Nasdaq, VIX    │  │  XLK, XLV, XLF...    │            │
│  └──────────────────────┘  └──────────────────────┘            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Signal Feed (Latest Signals)                            │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │ 🔍 DISCOVERY - $MU                                  │ │   │
│  │  │ Score: 70/100 | Catalyst: 50-day new high          │ │   │
│  │  │ Entry: $746.81 | Stop: $710 | Target: $820         │ │   │
│  │  │ Related News: [3 articles] | Earnings: [date]       │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ News Feed      │  │ Earnings Cal   │  │ Research Panel │   │
│  │ Latest 10 news │  │ Next 30 days   │  │ Kimi K Summary │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Refresh Schedule

```javascript
// Auto-refresh intervals
const REFRESH_INTERVALS = {
    signals: 60,           // 1 minute
    market_overview: 60,   // 1 minute
    news_feed: 300,        // 5 minutes
    sector_perf: 300,      // 5 minutes
    earnings: 3600,        // 1 hour
    research: 3600         // 1 hour
};
```

---

## CSS Styling

```css
/* Market Overview */
.market-overview {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
}

.index-card {
    background: #1a1a2e;
    border-left: 3px solid #00d4ff;
    padding: 1rem;
    border-radius: 4px;
}

.index-card .change.positive { color: #00ff41; }
.index-card .change.negative { color: #ff4757; }

/* News Article */
.news-article {
    background: #0f3460;
    border-left: 3px solid #00d4ff;
    padding: 1rem;
    margin-bottom: 1rem;
    border-radius: 4px;
}

.news-article.sentiment-positive {
    border-left-color: #00ff41;
}

.news-article.sentiment-negative {
    border-left-color: #ff4757;
}

.news-article.sentiment-neutral {
    border-left-color: #ffa502;
}

/* Sector Grid */
.sector-card {
    background: #1a1a2e;
    padding: 1rem;
    border-radius: 4px;
    text-align: center;
}

.sector-card.outperform {
    border: 2px solid #00ff41;
    background: rgba(0, 255, 65, 0.1);
}

.sector-card.underperform {
    border: 2px solid #ff4757;
    background: rgba(255, 71, 87, 0.1);
}
```

---

## Testing Checklist

- [ ] Research API endpoints respond correctly
- [ ] News aggregator fetches articles
- [ ] Earnings calendar displays upcoming earnings
- [ ] Market data shows latest indices
- [ ] Kimi K analysis generates results
- [ ] Frontend components render correctly
- [ ] Data refresh intervals working
- [ ] API keys properly configured
- [ ] Cache working (check timestamps)
- [ ] Error handling functioning

---

## Troubleshooting

### No news articles fetching
- Check Finnhub API key validity
- Verify API rate limits not exceeded
- Check cache TTL (15 minutes default)

### Earnings data missing
- Ensure FMP API key is valid
- Check if data is available for symbols
- Verify date range parameters

### Kimi K not responding
- Check Ollama Cloud URL configuration
- Verify model name (kimi-k2.5:cloud)
- Check timeout settings (60-90 seconds)

### Slow dashboard loading
- Reduce number of articles fetched
- Increase cache TTL values
- Use pagination for earnings calendar

---

**Ready for deployment**: All research components built and documented.
