# Robinhood Portfolio Integration Setup

Charlotte started integrating Robinhood portfolio tracking into the dashboard. Here's how to complete and run it.

## What's Included

✅ **Backend**
- `backend/robinhood_portfolio.py` — Robinhood API client with caching, async auth, position tracking
- `backend/portfolio_routes.py` — FastAPI endpoints for portfolio data
- `requirements.txt` — Already has `robin-stocks>=3.2.0`

✅ **Frontend**
- `frontend/src/components/PortfolioPanel.tsx` — React component with live position tracking
- `frontend/src/styles/PortfolioPanel.css` — Dark trading theme styling
- Integrated into `EnhancedDashboard.tsx` (appears in right column)

## Setup Steps

### 1. Set Robinhood Credentials

Add your Robinhood credentials to `.env`:

```bash
cd /tmp/trading-dashboard/backend
cat >> .env << EOF
ROBINHOOD_USERNAME=your_username
ROBINHOOD_PASSWORD=your_password
EOF
```

Or set as environment variables before running:

```bash
export ROBINHOOD_USERNAME="your_username"
export ROBINHOOD_PASSWORD="your_password"
```

### 2. Install Python Dependencies

```bash
cd /tmp/trading-dashboard/backend
pip install -r requirements.txt
```

**Note:** If you hit issues with `robin_stocks`:
- It requires Python 3.8+
- May need to install `cryptography` separately
- On WSL, you might need `python3-dev` for compilation

```bash
pip install cryptography
pip install robin-stocks --upgrade
```

### 3. Verify Backend Routes

Check that `main.py` includes the portfolio router. It should have:

```python
from portfolio_routes import portfolio_router
# ...
app.include_router(portfolio_router)
```

This is already done in the current version.

### 4. Start Backend (Local Testing)

```bash
cd /tmp/trading-dashboard/backend
python main.py
```

Or with Uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Build & Serve Frontend

```bash
cd /tmp/trading-dashboard/frontend
npm run build
npm run dev  # For local dev server on http://localhost:5173
```

## API Endpoints

Once running, these endpoints are available:

**GET /api/portfolio/** — Full portfolio summary
```bash
curl http://localhost:8000/api/portfolio/
```

**GET /api/portfolio/summary** — High-level overview (total value, positions count, gain/loss)

**GET /api/portfolio/positions** — List all positions with sorting
```bash
curl "http://localhost:8000/api/portfolio/positions?sort_by=value&limit=50"
```

**GET /api/portfolio/position/{symbol}** — Get specific position (e.g., `/api/portfolio/position/AAPL`)

**GET /api/portfolio/watchlist** — Get watchlist items

**GET /api/portfolio/performance** — Trading history (orders, win rate)
```bash
curl "http://localhost:8000/api/portfolio/performance?days=30"
```

**POST /api/portfolio/refresh** — Force cache refresh

**GET /api/portfolio/holdings-breakdown** — Portfolio allocation & concentration

**GET /api/portfolio/health** — Check auth status

## Frontend Features

The `PortfolioPanel` component displays:

✅ **Summary Stats**
- Total account value
- Buying power
- Available cash
- Position count

✅ **Position Cards** (with expansion)
- Symbol, quantity, current price
- Average buy price, current value
- Gain/loss ($ and %)
- Bid/ask spread
- P/E ratio, market cap (if available)
- Expandable detail view

✅ **Sorting & Filtering**
- Sort by: value, gain/loss, gain/loss %, symbol
- Limit positions shown

✅ **Live Refresh**
- Auto-refresh every 60 seconds
- Manual refresh button (🔄)
- Shows last update timestamp

## Troubleshooting

### "Not authenticated" error
- Check ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD are set
- Verify credentials are correct (case-sensitive)
- Check for API rate limiting (wait a minute and retry)

### `robin_stocks` import fails
```bash
pip install --upgrade pip setuptools wheel
pip install robin-stocks
```

### 2FA issues
- If your Robinhood account has 2FA enabled, the library may fail
- Workaround: Generate an app-specific password or disable 2FA temporarily
- Check robin_stocks documentation for 2FA support

### Slow responses
- First call loads from Robinhood API (~2-3 seconds)
- Subsequent calls use 5-minute cache
- Click refresh button to force new fetch

### CORS errors in browser
- Ensure frontend proxy is configured in `vite.config.js`
- Should have: `'/api': { target: 'http://localhost:8000' }`

## Deployment (DigitalOcean)

The `/tmp/trading-dashboard` repo auto-deploys to https://shaptech-3p3qo.ondigitalocean.app when you push to main.

To deploy:

```bash
cd /tmp/trading-dashboard
git add -A
git commit -m "Add: Robinhood portfolio tracking"
git push origin main
```

**DigitalOcean** will:
1. Pull latest code
2. Install dependencies
3. Build frontend (Vite)
4. Start backend (Uvicorn)

Once live, portfolio data will be available on production dashboard.

## Next Steps

- Test locally first before pushing to production
- Monitor API rate limits (Robinhood has daily limits)
- Consider adding portfolio performance charts (historical data)
- Add position alerts (e.g., notify when gain/loss hits threshold)
- Integrate with telegram signal bot for position updates

## Files Changed

```
backend/
  ├── robinhood_portfolio.py          [DONE - 14.7 KB]
  ├── portfolio_routes.py             [DONE - 9.5 KB]
  └── main.py                         [WIRED - already includes router]

frontend/
  ├── src/components/PortfolioPanel.tsx      [DONE - 9.6 KB]
  ├── src/styles/PortfolioPanel.css          [DONE - 5.8 KB]
  └── src/components/EnhancedDashboard.tsx   [PATCHED - added component]

requirements.txt                               [ALREADY HAS robin-stocks>=3.2.0]
```

---

**Status:** ✅ Ready to test locally, then deploy to production
