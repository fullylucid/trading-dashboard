"""Pytest bootstrap for the trading-dashboard backend test suite.

Sets test env defaults and makes ``backend/`` importable from any cwd.

The old ``client`` TestClient fixture (and ``test_smoke.py`` that used it) were
removed: a main.py refactor deleted the endpoints it asserted (/api/watchlist,
/api/regime) and dropped the module globals it patched, so it errored at setup AND
teardown and gave zero signal. Tests that need HTTP now build their own isolated
TestClient over just the router under test (see test_indicator_spec.py).
"""
import os
import sys
from pathlib import Path

# Set env before importing the app.
os.environ.setdefault("FINNHUB_API_KEY", "test_key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# Make backend/ importable when running `pytest` from backend/ or the repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
