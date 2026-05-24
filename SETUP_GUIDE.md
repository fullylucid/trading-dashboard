# Trading Research Dashboard - Setup & Deployment Guide

## Quick Start

### Backend Setup (5 minutes)

1. **Install Python Dependencies**
```bash
cd /tmp/trading-dashboard/backend
pip install -r requirements.txt
```

2. **Configure Environment Variables**
```bash
cat > .env << 'EOF'
FINNHUB_API_KEY=your_finnhub_api_key
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key
FMP_API_KEY=your_fmp_api_key
OLLAMA_CLOUD_API_KEY=your_ollama_key
OLLAMA_CLOUD_BASE_URL=https://api.ollama.cloud/v1
OLLAMA_CLOUD_MODEL=kimi-k-3-70b
EOF
```

3. **Start Backend Server**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Server will be available at: http://localhost:8000

**Interactive API Docs**: http://localhost:8000/docs

---

### Frontend Setup (5 minutes)

1. **Install Node Dependencies**
```bash
cd /tmp/trading-dashboard/frontend
npm install
```

2. **Start Development Server**
```bash
npm run dev
```

Frontend will be available at: http://localhost:5173

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Trading Dashboard                         │
├────────────────────────────────┬────────────────────────────┤
│                                │                            │
│      React Frontend            │     FastAPI Backend        │
│    (Port 5173)                 │    (Port 8000)             │
│                                │                            │
│  ┌──────────────────────┐     │  ┌──────────────────────┐  │
│  │ ComprehensiveDash    │     │  │ FastAPI Main App     │  │
│  │ - News Panel         │────────→ - CORS enabled        │  │
│  │ - Earnings Calendar  │     │  │ - API routes         │  │
│  │ - Research Panel     │     │  │ - Error handling     │  │
│  │ - Market Stats       │     │  │                      │  │
│  └──────────────────────┘     │  └──────────────────────┘  │
│                                │                            │
│      fetch('/api/*')           │  Services Layer:           │
│                                │  ┌──────────────────────┐  │
│                                │  │ NewsAggregator       │  │
│                                │  │ - Finnhub            │  │
│                                │  │ - Alpha Vantage      │  │
│                                │  │ - FMP                │  │
│                                │  └──────────────────────┘  │
│                                │                            │
│                                │  ┌──────────────────────┐  │
│                                │  │ EarningsCalendar     │  │
│                                │  │ - FMP API            │  │
│                                │  └──────────────────────┘  │
│                                │                            │
│                                │  ┌──────────────────────┐  │
│                                │  │ MarketData           │  │
│                                │  │ - Multiple APIs      │  │
│                                │  └──────────────────────┘  │
│                                │                            │
│                                │  ┌──────────────────────┐  │
│                                │  │ ResearchAgent        │  │
│                                │  │ - Ollama Cloud API   │  │
│                                │  │ - Kimi K Model       │  │
│                                │  └──────────────────────┘  │
│                                │                            │
└─────────────────────────────────────────────────────────────┘

                            ↓

┌──────────────────────────────────────────────────────────────┐
│           External APIs & Data Sources                       │
├──────────────────────────────────────────────────────────────┤
│ • Finnhub (News, Quotes)                                    │
│ • Alpha Vantage (News Sentiment, Breadth)                   │
│ • Financial Modeling Prep (Earnings, Financials)            │
│ • Ollama Cloud (Kimi K AI Model)                            │
└──────────────────────────────────────────────────────────────┘
```

---

## API Keys Setup

### 1. Finnhub API Key
- Go to: https://finnhub.io
- Sign up for free account
- Copy API key from dashboard
- Free tier: 60 requests/minute

### 2. Alpha Vantage API Key
- Go to: https://www.alphavantage.co
- Sign up for free account
- Copy API key from email
- Free tier: 5 requests/minute

### 3. Financial Modeling Prep (FMP) API Key
- Go to: https://financialmodelingprep.com
- Sign up for free account
- Copy API key from account settings
- Free tier: 250 requests/day

### 4. Ollama Cloud API Key
- Go to: https://ollama.ai
- Create account
- Get API key from settings
- Model: `kimi-k-3-70b` (free tier available)
- Base URL: `https://api.ollama.cloud/v1`

---

## Deployment Options

### Option 1: Docker Containerization

**Dockerfile for Backend**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

ENV FINNHUB_API_KEY=""
ENV ALPHA_VANTAGE_API_KEY=""
ENV FMP_API_KEY=""
ENV OLLAMA_CLOUD_API_KEY=""

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Build and Run**
```bash
docker build -t trading-dashboard-backend .
docker run -p 8000:8000 \
  -e FINNHUB_API_KEY=your_key \
  -e ALPHA_VANTAGE_API_KEY=your_key \
  -e FMP_API_KEY=your_key \
  -e OLLAMA_CLOUD_API_KEY=your_key \
  trading-dashboard-backend
```

### Option 2: Cloud Deployment (Heroku/Railway)

**For Backend (FastAPI)**
1. Create `Procfile`:
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

2. Deploy:
```bash
git push heroku main
```

3. Set environment variables:
```bash
heroku config:set FINNHUB_API_KEY=your_key
heroku config:set ALPHA_VANTAGE_API_KEY=your_key
heroku config:set FMP_API_KEY=your_key
heroku config:set OLLAMA_CLOUD_API_KEY=your_key
```

**For Frontend (React)**
1. Build:
```bash
npm run build
```

2. Deploy built `dist/` to Vercel, Netlify, or similar

---

## Testing Endpoints

### Health Check
```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "service": "Trading Dashboard API",
  "version": "1.0.0"
}
```

### Get Market Overview
```bash
curl http://localhost:8000/api/market/overview
```

### Get Market News
```bash
curl http://localhost:8000/api/news/market?limit=5
```

### Get Upcoming Earnings
```bash
curl http://localhost:8000/api/earnings/upcoming?days_ahead=30&limit=10
```

### Test Research Summarization
```bash
curl -X POST http://localhost:8000/api/research/summarize \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "content": "Apple Inc reported strong Q4 earnings. Revenue grew 5% YoY to $120B. Services segment grew 10% YoY.",
    "title": "Q4 2024 Earnings"
  }'
```

---

## Performance Tuning

### Backend Optimization

1. **Increase Worker Processes**
```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
```

2. **Enable Async Operations**
- Already implemented in code
- Uses `aiohttp` for concurrent API calls

3. **Database Connection Pool**
- Consider adding connection pool if using database
- Max connections: 20 (adjust based on load)

4. **Cache Configuration**
- News cache: 5 minutes
- Market data: 1 minute
- Earnings: 10 minutes
- Research: 24 hours

### Frontend Optimization

1. **Production Build**
```bash
npm run build
```

2. **Serve with Compression**
```bash
npm install -g serve
serve -s dist -l 3000
```

3. **Enable Service Workers**
- Add PWA manifest for offline support

---

## Monitoring & Logging

### Backend Logging

View logs in real-time:
```bash
tail -f /tmp/trading-dashboard/backend/logs.txt
```

### Frontend Console

Open browser DevTools (F12) → Console tab to see errors

### API Performance

Check cache stats:
```bash
curl http://localhost:8000/api/research/cache-stats
```

---

## Troubleshooting

### Issue: "Connection refused" when frontend tries to reach backend

**Solution:**
1. Verify backend is running on port 8000
2. Check proxy configuration in `vite.config.ts`
3. Ensure CORS is enabled in `main.py`

### Issue: API returns 401 Unauthorized

**Solution:**
1. Verify API keys are set in `.env`
2. Check API key validity with API provider
3. Ensure `export` statements worked:
```bash
echo $FINNHUB_API_KEY
```

### Issue: Slow API responses

**Solution:**
1. Check cache hit rates
2. Verify API rate limits not exceeded
3. Consider implementing request batching
4. Use CDN for static frontend assets

### Issue: "Module not found" errors in frontend

**Solution:**
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

---

## Security Considerations

1. **API Keys**
   - Never commit `.env` file to git
   - Rotate keys periodically
   - Use environment variables for secrets

2. **CORS**
   - Restrict to your domain in production
   - Update `CORS_ORIGINS` in `main.py`

3. **Rate Limiting**
   - Implement in production
   - Track API quota usage

4. **Data Validation**
   - Pydantic models validate input
   - Frontend sanitizes user input

---

## Environment Variables Reference

```bash
# Financial APIs
FINNHUB_API_KEY=               # https://finnhub.io
ALPHA_VANTAGE_API_KEY=         # https://alphavantage.co
FMP_API_KEY=                   # https://financialmodelingprep.com

# Ollama Cloud Configuration
OLLAMA_CLOUD_BASE_URL=https://api.ollama.cloud/v1
OLLAMA_CLOUD_API_KEY=          # https://ollama.ai
OLLAMA_CLOUD_MODEL=kimi-k-3-70b

# Optional
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
LOG_LEVEL=INFO
```

---

## Development Workflow

### Running Locally

Terminal 1 - Backend:
```bash
cd /tmp/trading-dashboard/backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Terminal 2 - Frontend:
```bash
cd /tmp/trading-dashboard/frontend
npm install
npm run dev
```

### Code Structure

- **Backend**: Each module is independent and testable
- **Frontend**: Component-based architecture
- **Styling**: CSS Modules per component
- **Types**: Full TypeScript types for frontend

---

## Testing

### Backend Tests (Example)
```python
import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
```

### Frontend Tests (Example)
```typescript
import { render, screen } from '@testing-library/react';
import NewsPanel from './NewsPanel';

test('renders news panel', () => {
  render(<NewsPanel />);
  expect(screen.getByText('Market News')).toBeInTheDocument();
});
```

---

## Next Steps

1. ✅ Set up API keys
2. ✅ Run backend server
3. ✅ Run frontend server
4. ✅ Test endpoints with curl
5. ✅ Open dashboard in browser
6. ✅ Search for stocks and upload reports

## Support

- **Documentation**: `/README_RESEARCH.md`
- **API Docs**: http://localhost:8000/docs
- **Issues**: Check logs and environment setup

---

**Version**: 1.0.0  
**Last Updated**: January 2024
