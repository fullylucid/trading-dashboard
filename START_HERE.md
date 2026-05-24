# 🚀 START HERE - Trading Research Dashboard

Welcome! This is a complete, production-ready Trading Research Dashboard. Here's how to get started:

## ⚡ Quick Start (5 minutes)

### 1. Read This First
**File**: `SETUP_GUIDE.md` (12KB)
- Complete setup instructions
- API key configuration
- 5-minute quick start

### 2. Get API Keys (2 minutes)
Visit these sites and get free API keys:
- **Finnhub**: https://finnhub.io (60 req/min free)
- **Alpha Vantage**: https://alphavantage.co (5 req/min free)
- **FMP**: https://financialmodelingprep.com (250 req/day free)
- **Ollama Cloud**: https://ollama.ai (For Kimi K AI model)

### 3. Install Dependencies (2 minutes)
```bash
# Backend
cd /tmp/trading-dashboard/backend
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 4. Configure API Keys (1 minute)
```bash
cd /tmp/trading-dashboard/backend
cat > .env << 'EOF'
FINNHUB_API_KEY=your_key_here
ALPHA_VANTAGE_API_KEY=your_key_here
FMP_API_KEY=your_key_here
OLLAMA_CLOUD_API_KEY=your_key_here
OLLAMA_CLOUD_BASE_URL=https://api.ollama.cloud/v1
OLLAMA_CLOUD_MODEL=kimi-k-3-70b
