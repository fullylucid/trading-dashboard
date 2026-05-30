"""Unit tests for the /api/portfolio/scan endpoint."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/ and repo root on sys.path for direct imports
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
HERMES_DIR = REPO_ROOT / "hermes"
for _p in (str(BACKEND_DIR), str(REPO_ROOT), str(HERMES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("FINNHUB_API_KEY", "test_key")


@pytest.fixture(autouse=True)
def _clear_scan_cache():
    import portfolio_routes
    portfolio_routes._SCAN_CACHE.clear()
    yield
    portfolio_routes._SCAN_CACHE.clear()


def _mk_dd(symbol, score):
    return {
        "symbol": symbol,
        "composite_score": score,
        "verdict": "Buy" if score >= 6.5 else "Hold" if score >= 4.5 else "Avoid",
        "scores": {"technical": score, "projection": score, "narrative": score, "combined": score},
        "quote": {"price": 100.0, "change_pct": 1.0, "volume": 1000},
        "projection": {"bear": 90, "base": 110, "bull": 130},
        "narrative": {},
        "breakdown": {"technical": {"score": score, "reason": "x"}, "projection": {"score": score}, "narrative": {"score": score}},
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_scan_filters_sorts_and_collects_failures():
    import portfolio_routes

    positions = [
        {"symbol": "AAPL", "quantity": 10, "market_value": 1000.0},
        {"symbol": "AAPL", "quantity": 5, "market_value": 500.0},   # dedup
        {"symbol": "MSFT", "quantity": 3, "market_value": 900.0},
        {"symbol": "NVDA", "quantity": 2, "market_value": 600.0},
        {"symbol": "BTC", "quantity": 1, "market_value": 50000.0},  # crypto, skip
        {"symbol": "BRK.B", "quantity": 1, "market_value": 400.0},  # non-matching regex, skip
        {"symbol": "FAIL", "quantity": 1, "market_value": 100.0},   # will raise
    ]

    mock_portfolio = MagicMock()
    mock_portfolio.get_positions = AsyncMock(return_value=positions)

    scores = {"AAPL": 7.5, "MSFT": 5.5, "NVDA": 3.0}

    async def fake_run_deep_dive(symbol, *, include_thesis=True, include_analytics=True):
        if symbol == "FAIL":
            raise RuntimeError("boom")
        return _mk_dd(symbol, scores[symbol])

    with patch.object(portfolio_routes, "get_portfolio_instance", AsyncMock(return_value=mock_portfolio)), \
         patch.object(portfolio_routes, "_run_deep_dive", side_effect=fake_run_deep_dive):
        result = await portfolio_routes.scan_portfolio(top_n=10, include_thesis=False, refresh=True)

    assert result["tickers_scanned"] == 3
    assert result["tickers_failed"] == 1
    assert result["failed"][0]["symbol"] == "FAIL"
    assert "boom" in result["failed"][0]["error"]

    ranked_syms = [r["symbol"] for r in result["ranked"]]
    assert ranked_syms == ["AAPL", "MSFT", "NVDA"]  # sorted desc by composite

    # AAPL dedup: units 10+5=15, market_value 1500
    aapl = next(r for r in result["ranked"] if r["symbol"] == "AAPL")
    assert aapl["units"] == 15
    assert aapl["market_value"] == 1500.0

    # Portfolio value = 1500 + 900 + 600 = 3000 (FAIL is included since it survived filter)
    assert result["portfolio_value"] == 3100.0

    # Buckets
    assert [r["symbol"] for r in result["top_buys"]] == ["AAPL"]
    assert [r["symbol"] for r in result["top_sells"]] == ["NVDA"]

    # Crypto + non-equity skipped
    assert "BTC" in result["skipped_symbols"]
    assert "BRK.B" in result["skipped_symbols"]


@pytest.mark.asyncio
async def test_scan_cache_hit_when_not_refresh():
    import portfolio_routes

    mock_portfolio = MagicMock()
    mock_portfolio.get_positions = AsyncMock(return_value=[
        {"symbol": "AAPL", "quantity": 10, "market_value": 1000.0},
    ])

    async def fake_dd(symbol, *, include_thesis=True, include_analytics=True):
        return _mk_dd(symbol, 7.0)

    with patch.object(portfolio_routes, "get_portfolio_instance", AsyncMock(return_value=mock_portfolio)), \
         patch.object(portfolio_routes, "_run_deep_dive", side_effect=fake_dd) as dd_mock:
        r1 = await portfolio_routes.scan_portfolio(top_n=5, include_thesis=False, refresh=False)
        r2 = await portfolio_routes.scan_portfolio(top_n=5, include_thesis=False, refresh=False)
        assert dd_mock.await_count == 1  # second call served from cache
        assert r1 is r2


@pytest.mark.asyncio
async def test_scan_include_thesis_runs_only_on_top_buys():
    import portfolio_routes

    positions = [
        {"symbol": f"SYM{i}", "quantity": 1, "market_value": 100.0}
        for i in range(7)
    ]
    # Make all valid 1-char tickers
    positions = [{"symbol": chr(ord("A") + i), "quantity": 1, "market_value": 100.0} for i in range(7)]
    score_map = {chr(ord("A") + i): 8.0 - i * 0.1 for i in range(7)}  # all >= 6.0 so top_buys has 5

    mock_portfolio = MagicMock()
    mock_portfolio.get_positions = AsyncMock(return_value=positions)

    async def fake_dd(symbol, *, include_thesis=True, include_analytics=True):
        return _mk_dd(symbol, score_map[symbol])

    thesis_calls = []

    def fake_thesis(symbol, *args, **kwargs):
        thesis_calls.append(symbol)
        return f"## Verdict\nBuy {symbol}", []

    with patch.object(portfolio_routes, "get_portfolio_instance", AsyncMock(return_value=mock_portfolio)), \
         patch.object(portfolio_routes, "_run_deep_dive", side_effect=fake_dd), \
         patch.object(portfolio_routes, "_generate_thesis", side_effect=fake_thesis):
        result = await portfolio_routes.scan_portfolio(top_n=20, include_thesis=True, refresh=True)

    # Only top 5 buys get thesis
    assert len(thesis_calls) == 5
    assert thesis_calls == [r["symbol"] for r in result["top_buys"]]
    for entry in result["top_buys"]:
        assert "thesis_markdown" in entry
        assert entry["thesis_model"] == portfolio_routes.THESIS_MODEL
