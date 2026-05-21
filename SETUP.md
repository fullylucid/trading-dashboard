# Trading Dashboard - Setup Guide

Complete step-by-step instructions for setting up and running the trading dashboard.

## Prerequisites

- **Python**: 3.11 or higher
- **Node.js**: 18 or higher  
- **pip**: Python package manager
- **npm**: Node package manager
- **Docker** (optional, for containerized deployment)
- **Finnhub API Key**: Free tier at https://finnhub.io

## 1. Get Your API Keys

### Finnhub (Required)
1. Go to https://finnhub.io
2. Sign up (free tier available)
3. Go to Dashboard → API Keys
4. Copy your API key (looks like: `d7276q1r01qjeeeg64c...`)

### Telegram Bot (Optional, for alerts)
1. Open Telegram
2. Talk to @BotFather
3. Create a new bot (`/newbot`)
4. Copy your bot token
5. Get your chat ID: Talk to @userinfobot

## 2. Clone or Navigate to Repository

```bash
# If you need to clone
git clone https://github.com/yourname/trading-dashboard.git
cd trading-dashboard

# Or navigate to existing
cd ~/.hermes/workspace/trading-dashboard
```

## 3. Quick Start (Recommended - Docker)

### Option A: Automated Setup
```bash
# Make script executable (if not already)
chmod +x start.sh

# Run complete Docker setup
./start.sh docker

# Check services running
docker-compose ps
```

### Option B: Manual Docker Setup
```bash
# Copy environment template
cp backend/.env.example .env

# Edit .env and add your API keys
nano .env
# Or on Windows: notepad .env

# Edit and set:
# FINNHUB_API_KEY=your_api_key_here

# Start services
docker-compose up -d

# View logs
docker-compose logs -f backend
```

Access the dashboard:
- **Frontend**: http://localhost:5000
- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

---

## 4. Local Development (Without Docker)

### Step 1: Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# Edit .env with your API keys
nano .env
# Add: FINNHUB_API_KEY=your_key_here

# Test installation
python -c "import fastapi; print('✓ FastAPI installed')"
```

### Step 2: Frontend Setup

```bash
cd ../frontend

# Install dependencies
npm install

# Create .env file (optional, uses defaults)
cp .env.example .env

# Test installation
npm list react
```

### Step 3: Start Services

**Terminal 1 - Backend:**
```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
python main.py

# You should see:
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm start

# You should see:
# Compiled successfully!
# Open http://localhost:3000 to view it in the browser.
```

Access the dashboard:
- **Frontend**: http://localhost:3000
- **API**: http://localhost:8000

---

## 5. Configuration

### Backend Configuration (backend/.env)

```bash
# Server Settings
DASHBOARD_ENV=development              # or 'production'
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000

# Required: Finnhub API Key
FINNHUB_API_KEY=your_api_key_here

# Optional: Redis (if not using Docker)
REDIS_URL=redis://localhost:6379/0

# Optional: Telegram Alerts
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Frontend URL for CORS
FRONTEND_URL=http://localhost:3000
```

### Frontend Configuration (frontend/.env)

```bash
# API URLs
REACT_APP_API_URL=http://localhost:8000
REACT_APP_WS_PRICES_URL=ws://localhost:8000/ws/prices
REACT_APP_WS_SIGNALS_URL=ws://localhost:8000/ws/signals

# Feature Flags
REACT_APP_ENABLE_LIVE_TRADING=false
REACT_APP_ENABLE_ALERTS=true
```

---

## 6. Testing

### API Health Check

```bash
# Test API is running
curl http://localhost:8000/api/health

# Expected response:
# {"status":"healthy","timestamp":"2024-01-15T..."}
```

### WebSocket Test

```bash
# Using websocat (install: cargo install websocat)
websocat ws://localhost:8000/ws/prices

# Or using curl
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  http://localhost:8000/ws/prices

# Should upgrade to WebSocket protocol
```

### Frontend Test

```bash
# Test frontend loads
curl http://localhost:3000

# Should return HTML content
```

---

## 7. Updating Watchlist

Edit your watchlist in the Hermes memory file:

```bash
nano ~/.hermes/MEMORY.md

# Add stocks to "High Conviction Watches" section:
# **SYMBOL (Company Name)**
# - Status: Description
# - Alert: Price levels
```

Backend automatically loads watchlist on startup.

---

## 8. Troubleshooting

### "Port already in use" Error

```bash
# Find what's using the port
# macOS/Linux:
lsof -i :8000    # For backend
lsof -i :3000    # For frontend

# Kill the process
kill -9 <PID>

# Or change port in .env
DASHBOARD_PORT=8001
```

### "ModuleNotFoundError: No module named 'fastapi'"

```bash
# Make sure virtual environment is activated
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Then reinstall
pip install -r requirements.txt
```

### "npm: command not found"

```bash
# Install Node.js from https://nodejs.org
# Or using package manager:
# macOS:
brew install node

# Ubuntu/Debian:
sudo apt install nodejs npm

# Verify installation
node --version
npm --version
```

### API returns "502 Bad Gateway"

```bash
# Check backend is running
ps aux | grep python

# Check logs
docker-compose logs backend

# Or restart
./start.sh docker-stop
./start.sh docker
```

### WebSocket connection refuses

```bash
# Check backend WebSocket is responding
curl -i -N http://localhost:8000/ws/prices

# If 404: Backend not running
# If 200: Connection working
```

### Redis connection error

```bash
# If using Docker: Redis starts automatically
# If local: Start Redis
redis-server

# Test connection
redis-cli ping
# Should return: PONG
```

---

## 9. Performance Tuning

### Reduce API Calls
```python
# In backend/config.py
SIGNAL_UPDATE_INTERVAL = 10  # Increase from 5 seconds
PRICE_UPDATE_INTERVAL = 1.0  # Increase from 0.5 seconds
CACHE_TTL = 600              # Increase from 300 seconds
```

### Increase Memory Cache (if no Redis)
```python
# In backend/cache_manager.py
# Larger in-memory cache improves performance
```

### Browser Dev Tools
```javascript
// Open browser console (F12)
// Check Network tab for slow requests
// Monitor WebSocket connections
```

---

## 10. Security Checklist

Before deploying to production:

- [ ] Create strong API keys (not shared in git)
- [ ] Use environment variables for all secrets
- [ ] Enable HTTPS/SSL
- [ ] Configure CORS origins
- [ ] Enable rate limiting
- [ ] Setup firewall rules
- [ ] Enable authentication for trading features
- [ ] Regular security updates

---

## 11. Next Steps

1. **Verify everything works:**
   ```bash
   ./start.sh docker        # Start services
   # Open http://localhost:5000
   ```

2. **Customize for your symbols:**
   - Edit ~/.hermes/MEMORY.md
   - Add your watchlist symbols

3. **Monitor alerts:**
   - View signal history in UI
   - Check logs: `docker-compose logs -f`

4. **Deploy to production:**
   - See deployment/DEPLOYMENT.md
   - Choose your cloud provider
   - Configure domains and SSL

5. **Setup alerts** (optional):
   - Add Telegram bot token to .env
   - Configure Discord webhooks
   - Setup email notifications

---

## 12. File Structure Reference

```
trading-dashboard/
├── backend/                    # Python FastAPI application
│   ├── main.py               # Main application
│   ├── config.py             # Configuration management
│   ├── data_fetcher.py       # Finnhub data streaming
│   ├── quant_bridge.py       # Quant-toolkit integration
│   ├── cache_manager.py      # Redis caching
│   ├── requirements.txt       # Python dependencies
│   ├── Dockerfile            # Docker image
│   └── .env.example          # Example config
│
├── frontend/                   # React web application
│   ├── src/
│   │   ├── components/       # React components
│   │   ├── pages/            # Page components
│   │   ├── store/            # State management (Zustand)
│   │   ├── App.jsx           # Main app component
│   │   └── index.jsx         # Entry point
│   ├── public/
│   │   └── index.html        # HTML template
│   ├── package.json          # Node dependencies
│   ├── Dockerfile            # Docker image
│   └── .env.example          # Example config
│
├── docker-compose.yml        # Container orchestration
├── nginx.conf                # Reverse proxy config
├── start.sh                  # Quick start script
├── README.md                 # Overview
└── deployment/               # Deployment guides
    └── DEPLOYMENT.md         # Detailed deployment
```

---

## 13. Getting Help

### Check Logs
```bash
# Docker logs
docker-compose logs backend
docker-compose logs frontend

# Application logs
tail -f ~/.hermes/logs/dashboard.log
tail -f ~/.hermes/logs/signals.jsonl
```

### Debug Mode
```bash
# Enable debug logging in backend/.env
DASHBOARD_ENV=development

# Frontend dev tools (F12)
# Check Network, Console tabs
```

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Port in use | Kill process or change port in .env |
| Module not found | Activate venv and run pip install |
| API timeout | Check internet, increase TIMEOUT in code |
| WebSocket error | Ensure backend is running on correct port |
| No data showing | Check Finnhub API key is valid |

---

## 14. Advanced Configuration

### Custom Indicators
Edit `backend/quant_bridge.py` to add custom technical indicators.

### Change Update Intervals
Edit `backend/config.py`:
```python
SIGNAL_UPDATE_INTERVAL = 5  # seconds between signal updates
PRICE_UPDATE_INTERVAL = 0.5  # seconds between price updates
```

### Customize UI Colors
Edit `frontend/src/App.css` - All uses Tailwind CSS classes.

### Add More Strategies
Modify `quant-toolkit.py` - Backend automatically integrates new strategies.

---

## 15. Production Checklist

Before going live:

- [ ] API keys secured (environment variables)
- [ ] SSL/TLS certificates installed
- [ ] Database backups configured
- [ ] Monitoring and alerting setup
- [ ] Rate limiting enabled
- [ ] Error logging configured
- [ ] Load testing completed
- [ ] Security audit performed

See `deployment/DEPLOYMENT.md` for detailed production setup.

---

## Support & Resources

- **Finnhub Docs**: https://finnhub.io/docs/api
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **React Docs**: https://react.dev
- **Docker Docs**: https://docs.docker.com
- **Nginx Docs**: https://nginx.org/en/docs

---

**You're all set! Start with:** `./start.sh docker`
