# TASK: Add a pytest smoke suite for the trading-dashboard backend

## Background

The FastAPI backend at `backend/main.py` has no tests. It deploys to DigitalOcean App Platform and a recent push silently broke `/api/health` because rate-limit decorators had bad signatures. We need a minimal pytest smoke suite that would catch that class of failure on every commit.

## Files

- **CREATE:** `backend/tests/__init__.py` (empty)
- **CREATE:** `backend/tests/test_smoke.py` — the smoke tests
- **CREATE:** `backend/tests/conftest.py` — pytest fixtures (FastAPI TestClient, mocked dependencies)
- **CREATE:** `backend/pytest.ini` — minimal config (testpaths, asyncio mode if needed)
- **EDIT:** `backend/requirements.txt` — add `pytest`, `pytest-asyncio`, `httpx` (FastAPI TestClient needs httpx)
- **READ-ONLY context:**
  - `backend/main.py` (515 lines, FastAPI app with these routes: `/api/health`, `/api/watchlist`, `/api/signals/{symbol}`, `/api/regime`, `/api/signals-history`, `/api/pnl`, `/api/chart-data/{symbol}`, `/ws/prices`, `/ws/signals`, `/`, `/{path:path}`)
  - `backend/config.py` — `Settings` (env-driven)
  - `backend/quant_bridge.py`, `backend/data_fetcher.py`, `backend/cache_manager.py` — modules that get initialized at startup

## Requirements

1. **Tests must run without real network or Redis.** Mock or stub:
   - `FinnhubPriceFetcher` (no real Finnhub API calls)
   - `QuantSignalBridge` (no calls to the toolkit)
   - `CacheManager` (in-memory fake; the existing one falls back if Redis isn't reachable — verify and use that fallback path, but the tests should not require redis running)

2. **Use FastAPI's `TestClient`** (sync) from `fastapi.testclient`. Don't bother with the WebSocket endpoints for v1 — REST only.

3. **The 5 tests to write:**
   - `test_health_endpoint_returns_200` — hits `/api/health`, asserts 200 and JSON shape includes `status` field.
   - `test_watchlist_endpoint_shape` — hits `/api/watchlist`, asserts 200 and response is a list (may be empty). Mock the watchlist loader if it reads from a file.
   - `test_signal_endpoint_with_unknown_symbol` — hits `/api/signals/UNKNOWN_SYMBOL_XYZ`, asserts it returns a reasonable response (200 with neutral signal OR 404 — whichever main.py does today; check the source).
   - `test_pnl_endpoint_returns_metric` — hits `/api/pnl`, asserts 200 and response includes `total_pnl` or similar key.
   - `test_root_serves_frontend_or_404` — hits `/`, asserts response is 200 (frontend served) OR 404 (no build) — both are valid in test env where no frontend build exists.

4. **conftest.py** must:
   - Set required env vars (`FINNHUB_API_KEY=test`, `REDIS_URL=redis://localhost:6379/0`, `LOG_DIR=/tmp`) BEFORE importing the app.
   - Provide a `client` fixture that yields a `TestClient(app)`.
   - Patch the network-touching modules so startup doesn't hang or fail.

5. **pytest.ini** — minimal:
   ```ini
   [pytest]
   testpaths = tests
   asyncio_mode = auto
   ```

## Constraints

- Do NOT modify `backend/main.py` to make it testable — work around it with fixtures, mocks, and env vars. If a test is genuinely impossible without touching main.py, skip it and document why in the test file.
- Tests must pass locally with `cd backend && pip install -r requirements.txt && pytest`.
- Total runtime should be < 10 seconds.
- Do NOT add a CI workflow yet — just the test files. (We'll wire CI in a follow-up.)

## Acceptance Criteria

- `cd backend && python -m pytest -v` runs and ALL 5 tests pass (or are skipped with a clear reason).
- No real network calls happen during the test run.
- `pytest --collect-only` reports exactly 5 tests collected from `tests/test_smoke.py`.

## Verify

```bash
cd /tmp/td-tests
pip install -r backend/requirements.txt
cd backend && python -m pytest -v --tb=short
echo "Exit: $?"
```
