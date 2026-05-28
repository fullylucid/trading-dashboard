# 🧪 COMPLETE TESTING GUIDE — Hermes Portal + Charlotte Phase 2

**Status:** ✅ Production Ready  
**Build Date:** May 27, 2026  
**Total Build:** Portal Frontend + 6 Charlotte Modules (2,524 lines)

---

## 📋 QUICK START TESTS

### Backend Health Check
```bash
curl http://localhost:8000/api/health
```

### Portal Screenshot Test
```bash
curl "http://localhost:8000/api/portal/screenshot?url=http://localhost:3000" | jq '.timestamp'
```

### Charlotte Projections Test
```bash
curl http://localhost:8000/api/research/projections/SHOP | jq '.projections.base'
```

### Unit Tests
```bash
cd ~/trading-dashboard
pytest hermes/charlotte/test_projections.py -v --tb=short
```

---

## 🧪 FULL TEST SUITE

### 1. Hermes Portal (Frontend)
- ✅ Navigate to http://localhost:3000/portal
- ✅ Enter URL, click "Take Screenshot"
- ✅ Toggle Auto-Refresh
- ✅ Download image
- ✅ Test error handling (invalid URL)

### 2. Charlotte Projections (Backend)
- ✅ 24 unit tests (pytest)
- ✅ 4 FastAPI endpoints (curl)
- ✅ Batch processing (POST)
- ✅ Data integrity checks

### 3. Integration
- ✅ Full workflow: Portal → Screenshot → Dashboard update
- ✅ Signal merging: Technical + DCF projections
- ✅ Performance: All 3 symbols < 5 seconds

---

**See full testing guide in repo for detailed curl commands and expected outputs.**