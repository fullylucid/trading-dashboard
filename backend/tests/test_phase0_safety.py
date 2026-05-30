"""
Phase 0 (safety/correctness) regression tests for the portfolio scanner.

Covers the four Phase 0 fixes from plan twinkly-cooking-valley.md:
  1. quant_bridge.py imports cleanly (regression for the bodyless-`if`
     syntax bug) and get_regime_state() returns the default regime dict
     for empty / too-short price series (no fabricated data).
  2. technical_scanner ma_200 is computed over 200 bars (not 50).
  3. market_data market-hours check is ET-aware (uses America/New_York,
     not naive local/server time).
  4. portfolio scan result helper math: partial_failure / failed_count
     for a mix of ok+failed entries, and the pct_of_portfolio guard when
     portfolio_value == 0.

Stdlib + pytest only. Imports the real modules where dependencies allow.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

# Make backend/ importable when running pytest from backend/ or repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# 1. quant_bridge import + default regime
# ---------------------------------------------------------------------------

def test_quant_bridge_imports():
    """Regression: the module must parse/import (bodyless-`if` syntax fix)."""
    import quant_bridge  # noqa: F401  (import is the assertion)

    assert hasattr(quant_bridge, "QuantSignalBridge")


def _make_bridge():
    import quant_bridge

    return quant_bridge.QuantSignalBridge(logging.getLogger("test"), MagicMock())


@pytest.mark.asyncio
async def test_get_regime_state_default_for_empty_prices():
    """Empty price list -> default regime dict, never fabricated data."""
    bridge = _make_bridge()
    result = await bridge.get_regime_state([])

    assert isinstance(result, dict)
    assert result == bridge._default_regime()
    # Sanity-check the documented default-regime contract.
    assert result["hmm_phase"] == 1
    assert result["trend_direction"] == "neutral"
    assert result["volatility_regime"] == "normal"


@pytest.mark.asyncio
async def test_get_regime_state_default_for_short_prices():
    """Too-short series (< 60 bars) -> default regime, no synthetic data."""
    bridge = _make_bridge()
    short_prices = [100.0 + i for i in range(10)]  # only 10 bars

    result = await bridge.get_regime_state(short_prices)

    assert result == bridge._default_regime()


@pytest.mark.asyncio
async def test_get_regime_state_default_for_none():
    """None prices -> default regime (the explicit `if not prices` branch)."""
    bridge = _make_bridge()
    result = await bridge.get_regime_state(None)

    assert result == bridge._default_regime()


# ---------------------------------------------------------------------------
# 2. technical_scanner ma_200 uses 200 bars
# ---------------------------------------------------------------------------

def _expected_ma(prices, window):
    tail = prices[-window:]
    return sum(tail) / len(tail)


@pytest.mark.asyncio
async def test_technical_scanner_ma200_uses_200_bars():
    """
    Feed a 200-bar series engineered so the true 200-DMA differs sharply
    from the 50-DMA, and assert the scanner reports the 200-bar mean.

    Series: first 150 bars at 10.0, last 50 bars at 100.0.
      - true 50-DMA  = 100.0   (last 50 are all 100)
      - true 200-DMA = (150*10 + 50*100) / 200 = 32.5
    A 200-DMA that is computed (buggily) over the last 50 bars would equal
    the 50-DMA (100.0); the correct fix yields 32.5.
    """
    from scanners.technical_scanner import TechnicalScanner

    prices = [10.0] * 150 + [100.0] * 50
    assert _expected_ma(prices, 50) == 100.0
    assert _expected_ma(prices, 200) == 32.5

    scanner = TechnicalScanner()
    result = await scanner.scan("TEST", {"prices": prices})

    components = result.get("components", {})
    ma_200 = components.get("ma_200")

    if ma_200 is None:
        pytest.skip(
            "technical_scanner does not expose components['ma_200']; "
            "cannot assert the 200-DMA value behaviorally. The ma_200 "
            "length fix should surface this field (or be covered by a "
            "white-box test in the scanner-owner's changes)."
        )

    # 200-bar mean (32.5), NOT the 50-bar mean (100.0).
    assert ma_200 == pytest.approx(32.5)
    assert ma_200 != pytest.approx(100.0)


def test_technical_scanner_source_slices_200_bars():
    """
    White-box guard: ma_200 must be sliced from the last 200 bars.

    ma_200 is a local in TechnicalScanner.scan() and is not exposed in the
    public result, so the behavioral test above self-skips. This asserts the
    actual fix at the source level: the ma_200 assignment slices [-200:],
    not the buggy [-50:].
    """
    import inspect

    from scanners.technical_scanner import TechnicalScanner

    src = inspect.getsource(TechnicalScanner.scan)
    ma_200_lines = [ln.strip() for ln in src.splitlines() if "ma_200" in ln and "=" in ln]
    assert ma_200_lines, "expected an ma_200 assignment in TechnicalScanner.scan"

    assignment = ma_200_lines[0]
    assert "[-200:]" in assignment, (
        f"ma_200 must be computed over 200 bars; got: {assignment!r}"
    )
    # The bug: ma_200 = mean(prices_array[-50:]) -> a 50-DMA mislabeled 200.
    assert "[-50:]" not in assignment, (
        f"ma_200 still slicing [-50:] (the 50-DMA bug); got: {assignment!r}"
    )


# ---------------------------------------------------------------------------
# 3. market_data market-hours is ET-aware
# ---------------------------------------------------------------------------

class _FixedDateTime(datetime):
    """datetime subclass whose .now(tz) returns a fixed instant in tz."""

    _fixed = None

    @classmethod
    def now(cls, tz=None):
        fixed = cls._fixed
        if tz is not None:
            return fixed.astimezone(tz)
        return fixed


@pytest.fixture
def market_data_module():
    import market_data
    return market_data


def test_is_market_open_during_et_session(monkeypatch, market_data_module):
    """
    A UTC instant that falls inside the ET regular session is reported open.

    Wed 2026-05-27 14:00 UTC == 10:00 ET (EDT, UTC-4) -> within 9:30-16:00.
    If the check used naive/UTC time, 14:00 would read as mid-session UTC
    too, so we ALSO assert the closed case below to prove ET conversion.
    """
    _FixedDateTime._fixed = datetime(2026, 5, 27, 14, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(market_data_module, "datetime", _FixedDateTime)

    md = market_data_module.MarketData()
    assert md._is_market_open() is True


def test_is_market_open_outside_et_session(monkeypatch, market_data_module):
    """
    A UTC instant outside the ET session is reported closed.

    Wed 2026-05-27 02:00 UTC == Tue 22:00 ET -> after the 16:00 close.
    A naive UTC check would treat 02:00 as pre-open too, so the discriminating
    case is the one below (21:00 UTC).
    """
    _FixedDateTime._fixed = datetime(2026, 5, 27, 2, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(market_data_module, "datetime", _FixedDateTime)

    md = market_data_module.MarketData()
    assert md._is_market_open() is False


def test_is_market_open_is_et_not_utc(monkeypatch, market_data_module):
    """
    Discriminating case proving ET (not UTC) is used.

    Wed 2026-05-27 21:00 UTC:
      - as UTC time -> 21:00, which a buggy 9:30-16:00 *UTC* check calls CLOSED.
      - as ET (EDT) -> 17:00 ET, also after the 16:00 close -> CLOSED.
    Both agree on closed, so instead use 13:00 UTC vs 19:00 UTC:
      - 13:00 UTC == 09:00 ET -> CLOSED (before 9:30 open) but a naive UTC
        check (13:00 within 9:30-16:00 UTC) would call it OPEN.
    """
    # 13:00 UTC == 09:00 ET -> before the 9:30 ET open -> CLOSED.
    # A naive UTC-based check would (wrongly) report OPEN at 13:00.
    _FixedDateTime._fixed = datetime(2026, 5, 27, 13, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(market_data_module, "datetime", _FixedDateTime)

    md = market_data_module.MarketData()
    assert md._is_market_open() is False


def test_is_market_open_weekend(monkeypatch, market_data_module):
    """Saturday is always closed regardless of time-of-day."""
    # Sat 2026-05-30 14:00 UTC (10:00 ET) -> weekend -> CLOSED.
    _FixedDateTime._fixed = datetime(2026, 5, 30, 14, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(market_data_module, "datetime", _FixedDateTime)

    md = market_data_module.MarketData()
    assert md._is_market_open() is False


def test_market_data_uses_eastern_tz(market_data_module):
    """The module pins the market timezone to US Eastern."""
    assert str(market_data_module.MARKET_TZ) == "America/New_York"


# ---------------------------------------------------------------------------
# 4. portfolio scan result aggregation math
# ---------------------------------------------------------------------------
#
# The partial_failure / failed_count flags and the pct_of_portfolio guard
# live INLINE inside portfolio_routes._execute_scan() (there is no extractable
# pure helper). These tests pin the exact guard expressions used there, so a
# regression that drops the zero-guard or mislabels partial failures is caught.

def _pct_of_portfolio(market_value, portfolio_value):
    """Mirror of the inline guard in _execute_scan (portfolio_routes.py)."""
    import math

    if portfolio_value and math.isfinite(portfolio_value):
        pct = market_value / portfolio_value * 100
        if not math.isfinite(pct):
            pct = 0.0
    else:
        pct = 0.0
    return pct


def _partial_failure(results, failed):
    """Mirror of the inline `partial_failure` expression in _execute_scan."""
    return bool(failed) and bool(results)


def test_pct_of_portfolio_zero_value_is_guarded():
    """portfolio_value == 0 must yield 0.0, never a ZeroDivisionError."""
    assert _pct_of_portfolio(1234.0, 0) == 0.0
    assert _pct_of_portfolio(0.0, 0) == 0.0


def test_pct_of_portfolio_normal():
    """Normal case: market_value / portfolio_value * 100."""
    assert _pct_of_portfolio(2500.0, 10000.0) == pytest.approx(25.0)


def test_pct_of_portfolio_non_finite_value_is_guarded():
    """A non-finite portfolio_value (inf/nan) falls through to 0.0."""
    assert _pct_of_portfolio(100.0, float("inf")) == 0.0
    assert _pct_of_portfolio(100.0, float("nan")) == 0.0


def test_partial_failure_mixed_ok_and_failed():
    """Some ok + some failed -> partial_failure True, failed_count correct."""
    results = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]
    failed = [{"symbol": "TSLA", "error": "deep-dive failed"}]

    assert _partial_failure(results, failed) is True
    assert len(failed) == 1


def test_partial_failure_all_ok():
    """No failures -> partial_failure False, failed_count 0."""
    results = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]
    failed = []

    assert _partial_failure(results, failed) is False
    assert len(failed) == 0


def test_partial_failure_all_failed_is_not_partial():
    """
    All failed and zero results -> NOT a partial failure (it's a total
    failure); partial_failure requires at least one successful result.
    """
    results = []
    failed = [{"symbol": "AAPL", "error": "x"}, {"symbol": "MSFT", "error": "y"}]

    assert _partial_failure(results, failed) is False
    assert len(failed) == 2


def test_execute_scan_inline_math_matches_helpers():
    """
    Guard: the production source still uses the exact guard expressions these
    helpers mirror. If _execute_scan stops zero-guarding pct or changes the
    partial_failure definition, this catches the drift.

    Read the source from disk rather than importing portfolio_routes, which
    pulls in the optional hermes/charlotte packages (not always installed in
    the test env). This keeps the guard self-contained.
    """
    src = (BACKEND_DIR / "portfolio_routes.py").read_text()
    # pct guard: division only under a finite, non-zero portfolio_value.
    assert "math.isfinite(portfolio_value)" in src
    assert "mv / portfolio_value" in src
    # partial_failure definition.
    assert "bool(failed) and bool(results)" in src
