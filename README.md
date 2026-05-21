# Trading Dashboard - Production-Ready Web Application

A real-time trading dashboard with WebSocket streaming, quantitative signal generation, and market regime analysis integrated with Tradeskeebot.

## Features

### Backend (FastAPI)
- **Live WebSocket Streaming**: Real-time price updates from Finnhub
- **Signal Generation**: Integrates with quant-toolkit.py for 7-strategy analysis
- **Market Regime Analysis**: HMM-based volatility and trend detection
- **REST API**: Full RESTful endpoints for watchlist, signals, charts, and P&L
- **Caching**: Redis-backed caching with in-memory fallback
- **Rate Limiting**: SlowAPI rate limiting for API endpoints
- **Structured Logging**: JSON-formatted logs for analytics
- **Error Handling**: Comprehensive error handling and recovery

### Frontend (React)
- **Live Watchlist**: Real-time ticker with price, change %, volume
- **7-Strategy Scoreboard**: Momentum, reversion, volatility, patterns, regime, correlation, leading indicators
- **Market Regime Visualization**: HMM phase, volatility regime, market heat
- **OHLC Charts**: TradingView Lightweight Charts with moving averages
- **Signal History**: 24-hour signal tracking with conversion rates
- **P&L Metrics**: Realized/unrealized P&L, Sharpe ratio, win rate
- **WebSocket Connections**: Real-time updates via WebSocket
- **Responsive Design**: Dark theme, mobile-friendly UI

### Integration
- **Watchlist**: Reads from `~/.hermes/MEMORY.md`
- **Quant Signals**: Calls `~/.hermes/scripts/quant-toolkit.py`
- **Logging**: Analytics to `~/.hermes/logs/dashboard.json`
- **Telegram**: Optional alert streaming via existing Telegram bot

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (for containerized deployment)
- Finnhub API key (free tier available at https://finnhub.io)

### Local Development

#### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

cp .env.example .env
# Edit .env and add your FINNHUB_API_KEY

pip install -r requirements.txt
python main.py
```

Backend runs on http://localhost:8000

#### 2. Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env

npm start
```

Frontend runs on http://localhost:3000

### Docker Deployment

```bash
# Create .env file with your API keys
cp backend/.env.example .env
echo "FINNHUB_API_KEY=your_key_here" >> .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

Access at:
- Frontend: http://localhost:5000
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## API Endpoints

### Health & Status
- `GET /api/health` - Health check

### Watchlist
- `GET /api/watchlist` - Get all watchlist items with live prices

### Signals
- `GET /api/signals/{symbol}` - Get latest signal for symbol
- `GET /api/signals-history` - Get 24-hour signal history
- `GET /api/regime` - Get market regime analysis

### Charts
- `GET /api/chart-data/{symbol}?lookback_days=30` - Get OHLCV data

### P&L
- `GET /api/pnl` - Get P&L metrics

### WebSocket
- `WS /ws/prices` - Real-time price stream
- `WS /ws/signals` - Real-time signal stream

## Configuration

### Environment Variables

**Backend (.env)**
```
FINNHUB_API_KEY=your_api_key
REDIS_URL=redis://localhost:6379/0
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
DASHBOARD_ENV=production
```

**Frontend (.env)**
```
REACT_APP_API_URL=http://localhost:8000
REACT_APP_WS_PRICES_URL=ws://localhost:8000/ws/prices
REACT_APP_WS_SIGNALS_URL=ws://localhost:8000/ws/signals
```

## Project Structure

```
trading-dashboard/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Settings management
│   ├── data_fetcher.py      # Finnhub WebSocket integration
│   ├── quant_bridge.py      # quant-toolkit integration
│   ├── cache_manager.py     # Redis caching
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── components/      # React components
│   │   │   ├── Navigation.jsx
│   │   │   ├── Watchlist.jsx
│   │   │   ├── QuantScoreboard.jsx
│   │   │   └── MarketRegime.jsx
│   │   ├── pages/           # Page components
│   │   │   ├── Dashboard.jsx
│   │   │   ├── ChartView.jsx
│   │   │   └── SignalHistory.jsx
│   │   ├── store/
│   │   │   └── useStore.js  # Zustand state management
│   │   ├── App.jsx
│   │   ├── App.css
│   │   └── index.jsx
│   ├── package.json
│   ├── Dockerfile
│   └── .env.example
├── docker-compose.yml
├── nginx.conf               # Production reverse proxy
└── README.md
```

## Production Deployment

### DigitalOcean App Platform

1. Push code to GitHub
2. Connect GitHub repo to DigitalOcean Apps
3. Create app.yaml:

```yaml
name: trading-dashboard
services:
- name: backend
  github:
    repo: your/repo
    branch: main
  build_command: pip install -r backend/requirements.txt
  run_command: cd backend && python main.py
  http_port: 8000
  envs:
  - key: FINNHUB_API_KEY
    scope: RUN_AND_BUILD_TIME
    value: ${FINNHUB_API_KEY}
  
- name: frontend
  github:
    repo: your/repo
    branch: main
  build_command: cd frontend && npm install && npm run build
  run_command: cd frontend && npx serve -s build -l 5000
  http_port: 5000

databases:
- name: redis
  engine: REDIS
  version: 7
```

### Traditional VPS (Nginx + Systemd)

1. **Setup server**
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y python3.11 python3-pip nodejs npm redis-server nginx
   ```

2. **Clone repository**
   ```bash
   git clone your-repo /opt/trading-dashboard
   cd /opt/trading-dashboard
   ```

3. **Setup backend**
   ```bash
   cd backend
   python3.11 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Create systemd service** (`/etc/systemd/system/trading-backend.service`)
   ```ini
   [Unit]
   Description=Trading Dashboard Backend
   After=network.target
   
   [Service]
   Type=simple
   User=trading
   WorkingDirectory=/opt/trading-dashboard/backend
   Environment="PATH=/opt/trading-dashboard/backend/venv/bin"
   ExecStart=/opt/trading-dashboard/backend/venv/bin/python main.py
   Restart=on-failure
   RestartSec=5s
   
   [Install]
   WantedBy=multi-user.target
   ```

5. **Setup frontend**
   ```bash
   cd /opt/trading-dashboard/frontend
   npm install
   npm run build
   npx serve -s build -l 5000
   ```

6. **Configure Nginx**
   ```bash
   sudo cp /opt/trading-dashboard/nginx.conf /etc/nginx/nginx.conf
   sudo systemctl reload nginx
   ```

7. **Start services**
   ```bash
   sudo systemctl start trading-backend
   sudo systemctl enable trading-backend
   ```

## Monitoring & Logs

### View Logs
```bash
# Backend logs
docker-compose logs -f backend

# Frontend logs
docker-compose logs -f frontend

# Structured logs (JSON)
tail -f ~/.hermes/logs/dashboard.log
tail -f ~/.hermes/logs/signals.jsonl
```

### Health Checks
```bash
curl http://localhost:8000/api/health
curl http://localhost:5000/
```

## Performance Optimization

### Caching Strategy
- Price data: 30 seconds TTL
- Signals: 5 minutes TTL
- Regime analysis: 5 minutes TTL
- Chart data: 1 hour TTL

### Rate Limiting
- API: 60 requests/minute per IP
- WebSocket: Unlimited (connection-based)

### Database Indexing
- Redis is fast enough for real-time data
- Consider PostgreSQL for historical analytics

## Troubleshooting

### Backend won't start
```bash
# Check Finnhub API key
echo $FINNHUB_API_KEY

# Check if port 8000 is free
lsof -i :8000

# Check logs
docker-compose logs backend
```

### WebSocket not connecting
```bash
# Check WebSocket endpoint
curl -i -N -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  http://localhost:8000/ws/prices
```

### High latency
1. Check Redis connectivity: `redis-cli ping`
2. Monitor CPU: `top`
3. Review Finnhub API rate limits

## Development

### Add New Strategy
1. Implement in quant-toolkit.py
2. Update QuantScoreboard component to display new score
3. Update signal model in main.py

### Add New Watchlist Symbol
Edit ~/.hermes/MEMORY.md and add to watchlist section. Backend auto-loads on startup.

### Customizing UI
Edit `frontend/src/components` React files. Tailwind CSS classes available.

## Security Considerations

1. **API Keys**: Never commit .env files. Use environment variables.
2. **CORS**: Configure allowed origins in config.py
3. **SSL/TLS**: Use Nginx with valid certificates in production
4. **Rate Limiting**: Enabled by default, adjust in config.py
5. **WebSocket Auth**: Consider adding token-based auth for production

## Future Enhancements

- [ ] Paper trading integration (Alpaca)
- [ ] Live trading execution (with safety limits)
- [ ] Advanced charting (TradingView Lightweight Charts)
- [ ] Backtesting framework
- [ ] Performance analytics
- [ ] Mobile app (React Native)
- [ ] Database persistence (PostgreSQL)
- [ ] Automated alerts (Discord, Slack)

## License

MIT

## Support

For issues, open an issue on GitHub or check the logs.

## Acknowledgments

- Finnhub for real-time market data
- Tradeskeebot for quant toolkit integration
- FastAPI & React communities
