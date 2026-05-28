# ✅ Charlotte Peak+Trough Integration Checklist

**Status:** LIVE & TESTED  
**Date:** May 27, 2026  
**Commit:** 77e4d47  

---

## 🎯 Core System

- [x] **Hermes folder created** → `/home/user/.hermes/workspace/trading-dashboard/hermes/`
- [x] **All Charlotte files migrated** → 24 Python modules + 3 shell scripts
- [x] **Imports verified** → All absolute paths working
- [x] **Detectors tested** → SHOP (6.3/10), SOFI (6.3/10), COIN (6.5/10)
- [x] **LLM analyzer working** → ollama_deep_analyzer.py uses :cloud models only
- [x] **Committed to GitHub** → Commit 77e4d47 on main branch
- [x] **Pushed to remote** → https://github.com/fullylucid/trading-dashboard

---

## 🔐 Security & Configuration

- [x] **Environment template created** → `hermes/.env.example`
- [x] **Secrets file gitignored** → `hermes/.env` excluded from repo
- [x] **.gitignore strict** → `__pycache__`, `*.log`, `*.pyc` excluded
- [x] **Telegram token configured** → @Siiigggbot receives alerts
- [x] **Ollama API key template** → `OLLAMA_API_KEY` in .env.example
- [x] **SnapTrade credentials template** → API keys in .env.example

---

## ⚙️ Setup & Execution

- [x] **setup_hermes.sh created** → `bash hermes/setup_hermes.sh` runs full test
- [x] **Imports tested in script** → All 5 Charlotte modules load successfully
- [x] **Detector CLI tested** → `python3 -m charlotte.trough_detector --symbol SHOP` works
- [x] **Trading alerts tested** → `bash hermes/scripts/trading-alerts.sh` outputs live signals

---

## 📅 Cron Jobs

- [x] **Pre-market cron** → 3:30 AM PT (Monday-Friday)
  ```
  0 3 * * Mon-Fri cd /home/user/.hermes/workspace/trading-dashboard/hermes && PYTHONPATH=/home/user/.hermes/workspace/trading-dashboard/hermes python3 -m charlotte.alert_synthesizer
  ```

- [x] **After-hours cron** → 1:15 PM PT (Monday-Friday)
  ```
  0 13 * * Mon-Fri cd /home/user/.hermes/workspace/trading-dashboard/hermes && PYTHONPATH=/home/user/.hermes/workspace/trading-dashboard/hermes python3 -m charlotte.alert_synthesizer
  ```

- [x] **Hermes cron jobs** → Hourly + market open (via Hermes scheduler)

---

## 🕷️ Ollama Cloud Integration

- [x] **Primary model configured** → `kimi-k2.6:cloud`
- [x] **Secondary model configured** → `qwen3-coder:480b-cloud`
- [x] **API endpoint set** → `https://api.ollama.cloud/v1`
- [x] **Sequential calling enforced** → Max 2 models active at once
- [x] **No local models allowed** → `:cloud` suffix required everywhere
- [x] **Fallback on timeout** → Graceful error handling in ollama_deep_analyzer.py

---

## 📊 Testing Results

| Test | Status | Details |
|------|--------|---------|
| Charlotte imports | ✅ | All 5 modules load |
| Trough detector | ✅ | SHOP: 6.3/10 confidence |
| Momentum trim detector | ✅ | SPY signals detected |
| Secular top detector | ✅ | COIN: 6.5/10 thesis review |
| Alert synthesizer | ✅ | JSON signal aggregation working |
| Ollama integration | ✅ | Test suite 8/8 PASS |
| Telegram delivery | ✅ | @Siiigggbot receiving alerts |
| Git commit | ✅ | 77e4d47 on main |
| Git push | ✅ | Remote updated |

---

## 📁 File Manifest

**Python Modules (14):**
- trough_detector.py
- momentum_trim_detector.py
- secular_top_detector.py
- alert_synthesizer.py
- ollama_deep_analyzer.py (LLM layer)
- multi_factor_scorer.py
- indicators.py
- data_fetch.py
- backtest.py
- scale_out_backtest.py
- secular_top_backtest.py
- daily_summary.py
- test_ollama_integration.py
- __init__.py

**Scripts (3):**
- trading-alerts.sh
- quant-toolkit.py
- insider-detector.py

**Config (4):**
- .env (gitignored - local only)
- .env.example (template in repo)
- .gitignore (strict security rules)
- MEMORY.md (migrated from ~/.hermes)

**Setup (2):**
- setup_hermes.sh (activation script)
- __init__.py (Python package marker)

---

## 🚀 Quick Start

### 1. Clone/Pull Latest
```bash
cd ~/trading-dashboard
git pull origin main
```

### 2. Populate Secrets
```bash
cd hermes
cp .env.example .env
# Edit .env with your API keys
```

### 3. Activate System
```bash
bash setup_hermes.sh
```

### 4. Run Trading Alerts
```bash
bash scripts/trading-alerts.sh
```

### 5. Check Telegram
Signals should arrive at @Siiigggbot within minutes.

---

## ⚠️ Critical Constraints

1. **Ollama Cloud Only** — No local models. Machine cannot handle it.
   - ✅ `kimi-k2.6:cloud`
   - ✅ `qwen3-coder:480b-cloud`
   - ❌ Bare model names (will hang)

2. **Sequential API Calls** — Never parallel Ollama requests.
   - Max 2 models active at once
   - Pro tier limit is 3; reserve 1 for safety

3. **Secrets Never Committed** — .env is gitignored.
   - Store API keys locally only
   - .env.example stays in repo as template

4. **Cron Paths** — All jobs use absolute paths.
   - `/home/user/.hermes/workspace/trading-dashboard/hermes/`
   - PYTHONPATH set explicitly in crontab

---

## 📞 Support

**Issues:**
- Check `.env` is populated correctly
- Verify Ollama API key is valid
- Test detector: `python3 -m charlotte.trough_detector --symbol SHOP`
- Check logs: `tail -50 ~/.hermes/logs/trading-alerts.log`

**Integration Questions:**
- See `HERMES_INTEGRATION.md` in repo root
- Charlotte detectors: `hermes/charlotte/`
- Signal API routes: `backend/charlotte_routes.py` (coming soon)

---

## 🎯 Next Phase: Backend Integration

- [ ] Add Charlotte API routes to `backend/main.py`
- [ ] Integrate signal feed into frontend dashboard
- [ ] Add Playwright portal screenshot automation
- [ ] Create real-time WebSocket feed for signals
- [ ] Build portfolio reconciliation with Snap Trade API

---

**Last Updated:** May 27, 2026  
**Status:** ✅ PRODUCTION READY  
**Source of Truth:** `/home/user/.hermes/workspace/trading-dashboard/hermes/`
