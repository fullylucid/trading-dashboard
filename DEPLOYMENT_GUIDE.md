# 🚀 DEPLOYMENT GUIDE — Hermes Portal + Charlotte Phase 2

**Build Date:** May 27, 2026  
**Status:** ✅ Production Ready  
**Total Commits:** 2 (Portal + Phase 2)

---

## LOCAL DEVELOPMENT SETUP

### Prerequisites
```bash
cd ~/trading-dashboard

# Install Python dependencies
pip install -r backend/requirements.txt

# Install Node dependencies
cd frontend && npm install && cd ..
```

### Start Services
```bash
# Terminal 1: Backend (FastAPI)
python3 backend/main.py
# Runs on http://localhost:8000

# Terminal 2: Frontend (React)
cd frontend && npm run dev
# Runs on http://localhost:3000
```

### Test Locally
```bash
# Portal screenshot
curl "http://localhost:8000/api/portal/screenshot?url=http://localhost:3000"

# Charlotte projections
curl http://localhost:8000/api/research/projections/SHOP

# Unit tests
pytest hermes/charlotte/test_projections.py -v
```

---

## DIGITAL OCEAN DEPLOYMENT (if needed)

### 1. Backend Setup
```bash
# SSH to DO app
ssh app@your-do-droplet

# Pull latest code
cd ~/trading-dashboard
git pull origin main

# Restart FastAPI (graceful)
pkill -f "uvicorn backend.main:app"
sleep 2
python3 backend/main.py --host 0.0.0.0 --port 8000 &
```

### 2. Frontend Build
```bash
# On your local machine
cd ~/trading-dashboard/frontend
npm run build
# Output: dist/

# Upload to DO
scp -r dist/* app@your-do-droplet:~/trading-dashboard/frontend/dist/
```

### 3. Nginx Configuration (DO)
```nginx
# /etc/nginx/sites-available/trading-dashboard
server {
    listen 80;
    server_name your-do-domain;

    # Frontend
    location / {
        root /home/app/trading-dashboard/frontend/dist;
        try_files $uri /index.html;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
    }
}
```

---

## KEY ENDPOINTS

### Portal
- `GET /api/portal/health` — Health check
- `GET /api/portal/screenshot?url=...` — Capture screenshot

### Charlotte
- `GET /api/research/projections/{symbol}` — Full DCF analysis
- `GET /api/research/charts/{symbol}` — Plotly JSON charts
- `GET /api/research/signal/enhanced/{symbol}` — Merged signal
- `POST /api/research/batch/projections` — Batch processing

---

## TROUBLESHOOTING

### Portal not capturing screenshots
```bash
# Check Playwright is working
python3 -c "from playwright.async_api import async_playwright; print('✓ Playwright OK')"
```

### Charlotte getting slow response
```bash
# Check yfinance is accessible
python3 -c "import yfinance as yf; print(yf.Ticker('SHOP').info['currentPrice'])"
```

### Frontend not loading Portal page
```bash
# Check App.jsx has /portal route
grep -n "HermesPortal" frontend/src/App.jsx
```

---

**All systems go. Ready for production. ✅**