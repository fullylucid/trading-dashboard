# Charlotte Phase 2 — QUICK START GUIDE

## ⚡ 5-Minute Setup

### 1. Install Dependencies
```bash
cd /home/user/.hermes/workspace/trading-dashboard/backend
pip install -r requirements.txt
```

### 2. Run Tests
```bash
cd /home/user/.hermes/workspace/trading-dashboard
pytest hermes/charlotte/test_projections.py -v
```

### 3. Start Server
```bash
cd backend && python3 main.py
# Server running on http://localhost:8000
```

### 4. Test an Endpoint
```bash
curl http://localhost:8000/api/research/projections/SHOP | jq .
```

---

## 🎯 Common Tasks

### Get DCF Projections Only
```python
from hermes.charlotte.projections import DCFProjector

p = DCFProjector('SHOP')
print(p.get_summary())
```

### Get Plotly Charts Only
```python
from hermes.charlotte.projections import DCFProjector
from hermes.charlotte.visualizer import PlotlyChartBuilder

p = DCFProjector('SHOP')
b = PlotlyChartBuilder(p)
charts = b.get_all_charts()
# Use in React: <PlotlyChart data={charts.charts.price_paths} />
```

### Get Enhanced Signal
```python
from hermes.charlotte.signal_engine_v2 import get_enhanced_signal

signal = get_enhanced_signal('SHOP')
print(f"{signal['type']} @ {signal['confidence']}/10 → ${signal['target']}")
```

### Batch Process 3 Symbols
```python
from hermes.charlotte.agents.charlotte_crew import run_batch_charlotte

results = run_batch_charlotte(['SHOP', 'SOFI', 'COIN'])
for analysis in results['analyses']:
    print(f"{analysis['symbol']}: {analysis['overall_status']}")
```

---

## 📊 API Endpoints Cheat Sheet

| Endpoint | Purpose | Example |
|----------|---------|---------|
| `GET /api/research/projections/{symbol}` | Full analysis | `/projections/SHOP` |
| `GET /api/research/charts/{symbol}` | Plotly charts | `/charts/SOFI` |
| `GET /api/research/signal/enhanced/{symbol}` | Merged signal | `/signal/enhanced/COIN` |
| `POST /api/research/batch/projections` | Multi-symbol | Body: `{"symbols": ["SHOP", ...]}` |

---

## 🧪 Quick Test Commands

```bash
# Test imports
python3 -c "from hermes.charlotte.projections import DCFProjector; print('✓')"

# Test full pipeline
python3 -c "from hermes.agents.charlotte_crew import run_full_charlotte; print(run_full_charlotte('SHOP')['overall_status'])"

# Run all tests
pytest hermes/charlotte/test_projections.py -v

# Run single test
pytest hermes/charlotte/test_projections.py::TestDCFProjector::test_calculate_price_targets -v
```

---

## 📁 File Map

```
hermes/charlotte/
├── projections.py           # DCFProjector class
├── visualizer.py            # PlotlyChartBuilder class
├── signal_enhancer.py       # EnhancedSignalEngine class
├── signal_engine_v2.py      # Public API functions
└── test_projections.py      # 24 unit tests

hermes/agents/
└── charlotte_crew.py        # LangChain orchestration

backend/
├── research_routes.py       # FastAPI endpoints (MODIFIED)
└── requirements.txt         # Dependencies (MODIFIED)
```

---

## 🔴 Troubleshooting

**Import Error: `No module named 'charlotte'`**
- Solution: Ensure sys.path includes `/home/user/.hermes/workspace/trading-dashboard/hermes`
- Check: `python3 -c "import sys; print('/hermes' in '\\n'.join(sys.path))"`

**API returns 500 error**
- Check server logs: `tail -f backend.log`
- Verify yfinance is working: `python3 -c "import yfinance; print(yfinance.Ticker('SHOP').info['regularMarketPrice'])"`

**Tests fail**
- Ensure all dependencies installed: `pip list | grep numpy pandas scipy plotly yfinance`
- Run with verbose: `pytest hermes/charlotte/test_projections.py -vv`

**No historical data**
- Check internet connection (yfinance needs network)
- Try different symbol: AAPL (most stable)

---

## 📚 Documentation

- **Full Docs:** See `CHARLOTTE_PHASE2_BUILD.md`
- **Deployment:** See `DEPLOYMENT_MANIFEST.md`
- **Code Examples:** See `hermes/charlotte/test_projections.py`

---

## 🚀 Next Steps

1. Deploy to staging server
2. Test all 4 endpoints
3. Monitor logs for errors
4. Load test with k6 or locust
5. Deploy to production

---

**Status:** ✅ READY TO USE  
**Date:** May 27, 2026
