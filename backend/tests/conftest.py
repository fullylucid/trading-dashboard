"""Pytest fixtures for trading-dashboard backend smoke tests."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Set env before importing app
os.environ.setdefault("FINNHUB_API_KEY", "test_key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# Make backend/ importable when running `pytest` from backend/ or repo root
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def client():
    """FastAPI TestClient with external deps mocked (no Redis, no Finnhub)."""
    from fastapi.testclient import TestClient
    import main

    # Mock cache_manager (Redis): always-empty cache
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock(return_value=True)
    mock_cache.connect = AsyncMock(return_value=True)
    mock_cache.disconnect = AsyncMock(return_value=None)
    mock_cache.client = MagicMock()  # for any direct attribute access

    # Mock price_fetcher (Finnhub)
    mock_price_fetcher = MagicMock()
    mock_price_fetcher.watchlist = ["AAPL", "MSFT", "TSLA"]
    mock_price_fetcher.start = AsyncMock(return_value=None)
    mock_price_fetcher.stop = AsyncMock(return_value=None)

    # Mock signal_bridge (QuantToolkit)
    mock_signal_bridge = MagicMock()
    mock_signal_bridge.generate_signal = AsyncMock(return_value=None)
    mock_signal_bridge.get_regime_state = AsyncMock(
        return_value={
            "hmm_phase": 1,
            "volatility_regime": "normal",
            "market_heat": 0.5,
            "trend_direction": "neutral",
            "estimated_probability": 0.5,
        }
    )

    with patch.object(main, "cache_manager", mock_cache), \
         patch.object(main, "price_fetcher", mock_price_fetcher), \
         patch.object(main, "signal_bridge", mock_signal_bridge):
        with TestClient(main.app) as test_client:
            yield test_client
