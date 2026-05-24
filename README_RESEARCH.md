# Trading Research Dashboard - Comprehensive Documentation

## Overview

The **Trading Research Dashboard** is an advanced web-based platform for financial market research, news aggregation, earnings calendar tracking, and AI-powered investment analysis. It combines real-time market data with AI-powered research using Kimi K (via Ollama Cloud) to provide actionable insights for traders and investors.

### Key Features

- **📰 Real-time News & Articles**: Market news, sector-specific news, earnings announcements, IPO updates, and merger information
- **🤖 AI Research Summarization**: Kimi K-powered summaries of research reports, earnings transcripts, and company analysis
- **📅 Earnings Calendar**: Upcoming earnings dates, historical earnings data, and earnings surprises
- **📊 Market Statistics**: Major indices (SPY, QQQ, DIA, IWM), sector performance, market breadth, VIX, treasuries, and commodities
- **💹 Sentiment Analysis**: AI-powered sentiment analysis of news and research documents
- **🎯 Dashboard Layout**: Multi-panel, responsive design with grid/list view options

---

## Architecture

### Backend Stack
- **Framework**: FastAPI (Python)
- **APIs**: Finnhub, Alpha Vantage, Financial Modeling Prep (FMP)
- **AI Engine**: Kimi K via Ollama Cloud API
- **Async**: asyncio + aiohttp for non-blocking API calls
- **Caching**: In-memory cache with TTL for performance

### Frontend Stack
- **Framework**: React with TypeScript
- **Styling**: CSS3 with responsive design
- **Components**: Modular, reusable React components
- **API Communication**: Fetch API for backend integration

---

## Project Structure

```
/tmp/trading-dashboard/
├── backend/
│   ├── main.py                  # FastAPI application entry point
│   ├── news_aggregator.py       # News fetching from multiple sources
│   ├── earnings_calendar.py     # Earnings event management
│   ├── market_data.py           # Market statistics and breadth
│   ├── research_agent.py        # Kimi K research summarization
│   ├── research_routes.py       # FastAPI route handlers
│   └── requirements.txt         # Python dependencies
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── NewsPanel.tsx                 # News feed component
│   │   │   ├── NewsPanel.css
│   │   │   ├── EarningsCalendar.tsx          # Earnings calendar component
│   │   │   ├── EarningsCalendar.css
│   │   │   ├── ResearchPanel.tsx             # Research/analysis component
│   │   │   ├── ResearchPanel.css
│   │   │   ├── MarketStats.tsx               # Market data component
│   │   │   ├── MarketStats.css
│   │   │   ├── ComprehensiveDashboard.tsx    # Main dashboard layout
│   │   │   └── ComprehensiveDashboard.css
│   │   ├── App.tsx
│   │   └── index.tsx
│   ├── package.json
│   └── tsconfig.json
│
└── README_RESEARCH.md           # This file
```

---

## Backend Components

### 1. **news_aggregator.py**

Fetches news from multiple financial data sources.

#### Key Classes:
- **`NewsArticle`**: Data model for news articles
- **`NewsAggregator`**: Main aggregation engine

#### Supported Sources:
- **Finnhub API**: General market news and company-specific news
- **Alpha Vantage**: News sentiment data
- **Financial Modeling Prep**: Categorized news (IPO, earnings, mergers)

#### Main Methods:
```python
# Fetch general market news
articles = await aggregator.fetch_market_news(limit=20)

# Fetch news for specific symbol
articles = await aggregator.fetch_symbol_news("AAPL", limit=20)

# Fetch sector news
articles = await aggregator.fetch_sector_news("Technology", limit=15)

# Fetch by category
articles = await aggregator.fetch_news_by_category(NewsCategory.EARNINGS)
```

#### Caching:
- 5-minute TTL cache to reduce API calls
- Automatic cache invalidation

---

### 2. **earnings_calendar.py**

Manages earnings events, estimates, and actual results.

#### Key Classes:
- **`EarningsEvent`**: Earnings data model
- **`EarningsCalendar`**: Earnings management engine

#### Main Methods:
```python
# Get upcoming earnings in next 30 days
events = await calendar.get_upcoming_earnings(days_ahead=30)

# Get historical earnings for symbol
history = await calendar.get_symbol_earnings_history("AAPL", limit=8)

# Get recent surprises (beats/misses)
surprises = await calendar.get_earnings_surprises(days=30)
```

#### Data Provided:
- Event date and fiscal quarter
- EPS estimates vs actuals
- Revenue estimates vs actuals
- Surprise percentages
- Status (upcoming/reported/surprise)

---

### 3. **market_data.py**

Fetches market-wide statistics and indicators.

#### Key Classes:
- **`MarketData`**: Market statistics engine
- **`MarketBreadth`**: Breadth indicators
- **`SectorData`**: Sector performance

#### Main Methods:
```python
# Get major indices
overview = await market.get_market_overview()  # SPY, QQQ, DIA, IWM

# Get sector performance
sectors = await market.get_sector_performance()

# Get market breadth (advances/declines)
breadth = await market.get_market_breadth()

# Get VIX volatility index
vix = await market.get_vix_data()

# Get treasury yields
treasuries = await market.get_treasuries()

# Get commodity prices
commodities = await market.get_commodities()
```

#### Sector Coverage:
- Technology, Healthcare, Financials, Industrials
- Consumer Discretionary, Consumer Staples, Energy
- Utilities, Materials, Real Estate, Communications

---

### 4. **research_agent.py**

AI-powered research summarization using Kimi K via Ollama Cloud.

#### Key Classes:
- **`ResearchSummary`**: Summary data model
- **`ResearchAgent`**: Kimi K integration engine

#### Main Methods:
```python
# Summarize research report
summary = await agent.summarize_research_report(
    symbol="AAPL",
    report_content="[Full report text...]",
    report_title="Q4 Earnings Report"
)

# Analyze earnings report
analysis = await agent.analyze_earnings_report(
    symbol="AAPL",
    earnings_text="[Earnings transcript...]"
)

# Generate investment thesis
thesis = await agent.generate_investment_thesis(
    symbol="AAPL",
    company_info="[Company background...]"
)

# Sentiment analysis
sentiment = await agent.sentiment_analysis(
    text="[News or report text...]",
    symbols=["AAPL", "MSFT"]
)
```

#### Features:
- JSON-formatted outputs
- Bullish/bearish/neutral sentiment classification
- Confidence scoring (0-1)
- Key points extraction
- 24-hour cache for summaries

#### Ollama Cloud Integration:
```python
config = {
    'base_url': 'https://api.ollama.cloud/v1',
    'api_key': 'your_api_key',
    'model': 'kimi-k-3-70b'
}
agent = ResearchAgent(config)
```

---

### 5. **research_routes.py**

FastAPI route handlers for all research endpoints.

#### API Endpoints:

**News Routes (`/api/news`):**
- `GET /market` - General market news
- `GET /symbol/{symbol}` - Symbol-specific news
- `GET /sector/{sector}` - Sector news
- `GET /category/{category}` - Categorized news

**Earnings Routes (`/api/earnings`):**
- `GET /upcoming` - Upcoming earnings
- `GET /history/{symbol}` - Earnings history
- `GET /surprises` - Recent surprises

**Market Routes (`/api/market`):**
- `GET /overview` - Major indices
- `GET /sectors` - Sector performance
- `GET /breadth` - Market breadth
- `GET /vix` - VIX data
- `GET /treasuries` - Treasury yields
- `GET /commodities` - Commodity prices

**Research Routes (`/api/research`):**
- `POST /summarize` - Research summarization
- `POST /earnings-analysis` - Earnings analysis
- `POST /investment-thesis` - Investment thesis generation
- `POST /sentiment` - Sentiment analysis
- `GET /cache-stats` - Cache statistics

---

### 6. **main.py**

FastAPI application entry point with service initialization.

#### Configuration:
```python
# Environment variables required:
FINNHUB_API_KEY         # Finnhub API key
ALPHA_VANTAGE_API_KEY   # Alpha Vantage API key
FMP_API_KEY             # Financial Modeling Prep API key
OLLAMA_CLOUD_API_KEY    # Ollama Cloud API key
OLLAMA_CLOUD_BASE_URL   # Ollama Cloud endpoint
OLLAMA_CLOUD_MODEL      # Model name (default: kimi-k-3-70b)
```

#### Startup:
```bash
export FINNHUB_API_KEY=your_key
export ALPHA_VANTAGE_API_KEY=your_key
export FMP_API_KEY=your_key
export OLLAMA_CLOUD_API_KEY=your_key

uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Frontend Components

### 1. **NewsPanel.tsx**

Displays news articles with filtering and sorting.

#### Props:
```typescript
interface NewsPanelProps {
  symbol?: string;           // Filter by symbol
  category?: NewsCategory;   // Filter by category
  limit?: number;           // Number of articles (default: 20)
}
```

#### Features:
- Real-time news feed
- Category filtering (market, earnings, IPO, merger)
- Sorting (by date or impact)
- Sentiment color-coding
- Relative time formatting
- Click-through to original articles

---

### 2. **EarningsCalendar.tsx**

Displays earnings events with estimates vs actuals.

#### Props:
```typescript
interface EarningsCalendarProps {
  daysAhead?: number;      // Look-ahead period (default: 30)
  limit?: number;          // Events to display (default: 100)
  showHistory?: boolean;   // Show historical view
  symbol?: string;         // Filter by symbol
}
```

#### Features:
- Upcoming earnings view
- Historical earnings view
- Earnings surprises view
- Estimate vs actual comparison
- Color-coded surprises (beat/miss/in-line)
- Beat/miss percentage calculations

---

### 3. **ResearchPanel.tsx**

AI-powered research summaries and analysis.

#### Props:
```typescript
interface ResearchPanelProps {
  symbol: string;           // Stock symbol
  reportContent?: string;   // Research report text
}
```

#### Features:
- AI-generated summaries (Kimi K)
- Key points extraction
- Sentiment analysis
- Earnings analysis
- Bullish/bearish/neutral classification
- Confidence scoring
- Tabbed interface (Summary/Earnings/Sentiment)

---

### 4. **MarketStats.tsx**

Market-wide statistics and indicators.

#### Features:
- Major indices (SPY, QQQ, DIA, IWM)
- VIX volatility index with status
- Sector performance with color-coding
- Market breadth visualization (advances/declines)
- Treasury yield curves (2Y, 5Y, 10Y, 30Y)
- Commodity prices (Oil, Gold, Natural Gas)
- Auto-refresh every 60 seconds
- Color-coded positive/negative changes

---

### 5. **ComprehensiveDashboard.tsx**

Main dashboard layout and navigation.

#### Features:
- Multi-panel layout
- Grid/list view toggle
- Symbol search and selection
- Research report upload
- Tab navigation (Overview/Symbol/Earnings/Research)
- Responsive sidebar with quick links
- Market status widget
- Feature showcase

#### Layout Modes:
- **Overview**: Market stats + recent news + earnings
- **Symbol-Specific**: News + earnings history + research upload
- **Earnings**: Full earnings calendar (90-day view)
- **Research**: AI analysis of uploaded reports

---

## API Integration Examples

### Fetch Market News
```bash
curl http://localhost:8000/api/news/market?limit=10
```

Response:
```json
[
  {
    "id": "finnhub_12345",
    "title": "Apple Reports Strong Q4 Earnings",
    "summary": "Apple exceeded expectations...",
    "source": "Finnhub",
    "url": "https://...",
    "published_at": "2024-01-15T10:30:00",
    "category": "earnings",
    "symbols": ["AAPL"],
    "sentiment": "positive",
    "impact_score": 0.85
  }
]
```

### Fetch Earnings Calendar
```bash
curl http://localhost:8000/api/earnings/upcoming?days_ahead=30&limit=20
```

### Get Market Overview
```bash
curl http://localhost:8000/api/market/overview
```

Response:
```json
{
  "SPY": {
    "symbol": "SPY",
    "price": 450.25,
    "change": 2.50,
    "change_pct": 0.56
  },
  ...
}
```

### Summarize Research Report
```bash
curl -X POST http://localhost:8000/api/research/summarize \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "content": "[Full report text...]",
    "title": "Q4 2024 Analysis"
  }'
```

Response:
```json
{
  "symbol": "AAPL",
  "title": "Strong Revenue Growth",
  "summary": "Apple showed strong growth in services...",
  "key_points": [
    "Services revenue grew 15% YoY",
    "Hardware sales declined 5%",
    "Margin expansion of 200 bps"
  ],
  "sentiment": "bullish",
  "confidence": 0.92,
  "generated_at": "2024-01-15T10:45:00"
}
```

---

## Installation & Setup

### Backend Setup

1. **Install Dependencies**
```bash
cd /tmp/trading-dashboard/backend
pip install -r requirements.txt
```

Required packages:
- fastapi
- uvicorn
- aiohttp
- pydantic
- python-dotenv

2. **Configure Environment**
```bash
# Create .env file
cat > .env << EOF
FINNHUB_API_KEY=your_finnhub_key
ALPHA_VANTAGE_API_KEY=your_av_key
FMP_API_KEY=your_fmp_key
OLLAMA_CLOUD_API_KEY=your_ollama_key
OLLAMA_CLOUD_BASE_URL=https://api.ollama.cloud/v1
OLLAMA_CLOUD_MODEL=kimi-k-3-70b
EOF
```

3. **Run Backend**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Visit http://localhost:8000/docs for interactive API docs.

### Frontend Setup

1. **Install Dependencies**
```bash
cd /tmp/trading-dashboard/frontend
npm install
```

2. **Configure Backend URL**
```typescript
// In components, use:
const API_BASE = 'http://localhost:8000'
```

3. **Run Development Server**
```bash
npm start
# or for Vite:
npm run dev
```

---

## Data Flow

### News Pipeline
1. FastAPI endpoint receives request
2. NewsAggregator checks cache
3. If cache miss, fetches from Finnhub/Alpha Vantage/FMP
4. Normalizes data to NewsArticle format
5. Stores in cache (5-min TTL)
6. Returns JSON response
7. Frontend renders with sentiment colors

### Research Analysis Pipeline
1. Frontend sends report content to `/api/research/summarize`
2. ResearchAgent calls Ollama Cloud API
3. Kimi K model processes report
4. Parses JSON response
5. Caches summary (24-hour TTL)
6. Frontend displays in tabbed interface

### Market Data Pipeline
1. MarketData service checks cache
2. Fetches quotes from Finnhub/Alpha Vantage
3. Calculates sector ETF performance
4. Retrieves breadth from Alpha Vantage
5. Formats into responses
6. Frontend auto-refreshes every 60 seconds

---

## Performance Optimization

### Caching Strategy
- **News**: 5-minute cache
- **Earnings**: 10-minute cache
- **Market Data**: 1-minute cache
- **Research Summaries**: 24-hour cache

### Async Operations
- All API calls are async (aiohttp)
- Concurrent fetching from multiple sources
- Non-blocking database operations

### Frontend Optimization
- Component lazy loading
- CSS Grid/Flexbox for performance
- Efficient state management
- Minimal re-renders

---

## API Keys & Configuration

### Required API Keys

**Finnhub** (https://finnhub.io)
- Sign up for free tier
- Get real-time news and quotes
- Rate limit: 60 req/min (free)

**Alpha Vantage** (https://www.alphavantage.co)
- Stock market news sentiment
- Market breadth indicators
- Rate limit: 5 req/min (free)

**Financial Modeling Prep** (https://financialmodelingprep.com)
- Earnings calendar and surprises
- Categorized news (IPO, merger)
- Rate limit: 250 req/day (free)

**Ollama Cloud** (https://ollama.ai)
- Kimi K model access
- Research summarization
- Setup endpoint: https://api.ollama.cloud/v1

---

## Troubleshooting

### Issue: API Key Errors
**Solution**: Verify environment variables are set:
```bash
echo $FINNHUB_API_KEY
echo $OLLAMA_CLOUD_API_KEY
```

### Issue: Ollama Cloud Connection Failed
**Solution**: Check API endpoint and authentication:
```bash
curl -H "Authorization: Bearer YOUR_KEY" https://api.ollama.cloud/v1/models
```

### Issue: Frontend Can't Connect to Backend
**Solution**: Check CORS configuration and port:
```bash
# Backend must run on 8000
# Frontend on 3000 or 5173 (Vite)
# Check CORS origins in main.py
```

### Issue: Slow API Responses
**Solution**: Check cache hit rates:
```bash
curl http://localhost:8000/api/research/cache-stats
```

---

## Future Enhancements

1. **Portfolio Tracking**: Add personal portfolio management
2. **Alert System**: Price alerts, earnings alerts, news alerts
3. **Technical Analysis**: Chart patterns, moving averages, RSI
4. **Options Data**: Options chains and implied volatility
5. **Backtesting**: Strategy backtesting framework
6. **User Auth**: Login system for personal dashboards
7. **Database**: Persistent storage for user data
8. **Real-time WebSockets**: Live data streaming

---

## Support & Documentation

- **API Docs**: http://localhost:8000/docs
- **Finnhub Docs**: https://finnhub.io/docs/api
- **Alpha Vantage Docs**: https://www.alphavantage.co/documentation/
- **FMP Docs**: https://financialmodelingprep.com/developer/docs

---

## License

This project is provided as-is for educational and research purposes.

**Disclaimer**: This dashboard is for informational purposes only and should not be considered as financial advice. Always conduct your own due diligence before making investment decisions.

---

## Version History

- **v1.0.0** (2024-01-15): Initial release with news, earnings, market data, and research components
