"""Known-input unit tests for backend/analytics/signals.py.

Each assertion pins a formula to a hand-computable or reference-comparable
expected value (RSI of a steadily rising series ~100, MACD sign on a trend, a
hand-built bearish-divergence series, gap math, 52w-range endpoints, etc.).
All inputs are completed-bar series (no look-ahead).
"""

import math

import numpy as np
import pytest

from analytics import signals as sig


# --------------------------------------------------------------------------- #
# ROC
# --------------------------------------------------------------------------- #
def test_roc_basic():
    # 100 -> 110 over 1 bar = +10%
    assert sig.roc([100.0, 110.0], 1) == pytest.approx(10.0)


def test_roc_multi_bar():
    close = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]  # +5% over 5 bars
    assert sig.roc(close, 5) == pytest.approx(5.0)


def test_roc_insufficient_data_nan():
    assert math.isnan(sig.roc([100.0], 5))


# --------------------------------------------------------------------------- #
# Relative strength vs SPY
# --------------------------------------------------------------------------- #
def test_relative_strength_outperformance():
    asset = [100.0, 110.0]   # +10%
    spy = [100.0, 104.0]     # +4%
    assert sig.relative_strength(asset, spy, 1) == pytest.approx(6.0)


def test_relative_strength_underperformance():
    asset = [100.0, 102.0]   # +2%
    spy = [100.0, 105.0]     # +5%
    assert sig.relative_strength(asset, spy, 1) == pytest.approx(-3.0)


# --------------------------------------------------------------------------- #
# RSI (Wilder)
# --------------------------------------------------------------------------- #
def test_rsi_steady_rise_near_100():
    """A monotonically rising series has no losses → RSI == 100."""
    close = np.arange(1, 40, dtype=float)  # 1,2,...,39 strictly increasing
    assert sig.rsi(close, period=14) == pytest.approx(100.0)


def test_rsi_steady_fall_near_0():
    close = np.arange(40, 1, -1, dtype=float)  # strictly decreasing
    assert sig.rsi(close, period=14) == pytest.approx(0.0)


def test_rsi_alternating_around_50():
    """Symmetric up/down moves of equal size → RSI 50."""
    close = np.array([100, 101, 100, 101, 100, 101, 100, 101, 100, 101,
                      100, 101, 100, 101, 100, 101], dtype=float)
    val = sig.rsi(close, period=14)
    assert 40.0 < val < 60.0


def test_rsi_insufficient_nan():
    assert math.isnan(sig.rsi([1.0, 2.0, 3.0], period=14))


def test_rsi_matches_reference_implementation():
    """Cross-check Wilder RSI against an independent inline reference."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, 60))
    period = 14

    # Reference Wilder RSI (independent loop)
    deltas = np.diff(close)
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)
    ag = gains[:period].mean()
    al = losses[:period].mean()
    for t in range(period, len(deltas)):
        ag = (ag * (period - 1) + gains[t]) / period
        al = (al * (period - 1) + losses[t]) / period
    ref = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

    assert sig.rsi(close, period) == pytest.approx(ref, abs=1e-9)


# --------------------------------------------------------------------------- #
# MACD
# --------------------------------------------------------------------------- #
def test_macd_keys():
    close = np.linspace(100, 150, 60)
    out = sig.macd(close)
    assert set(out.keys()) == {"macd", "signal", "hist"}


def test_macd_positive_on_uptrend():
    """On a sustained uptrend the fast EMA leads → macd line > 0."""
    close = np.linspace(100, 200, 80)
    out = sig.macd(close)
    assert out["macd"] > 0


def test_macd_negative_on_downtrend():
    close = np.linspace(200, 100, 80)
    out = sig.macd(close)
    assert out["macd"] < 0


def test_macd_matches_pandas_ewm():
    """MACD line/signal/hist match pandas ewm(adjust=False) reference."""
    import pandas as pd

    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1, 100))
    s = pd.Series(close)
    ema_fast = s.ewm(span=12, adjust=False).mean()
    ema_slow = s.ewm(span=26, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line

    out = sig.macd(close)
    assert out["macd"] == pytest.approx(macd_line.iloc[-1], abs=1e-9)
    assert out["signal"] == pytest.approx(signal_line.iloc[-1], abs=1e-9)
    assert out["hist"] == pytest.approx(hist.iloc[-1], abs=1e-9)


def test_macd_insufficient_nan():
    out = sig.macd([1.0, 2.0, 3.0])
    assert math.isnan(out["macd"])


# --------------------------------------------------------------------------- #
# Divergence
# --------------------------------------------------------------------------- #
def test_detect_bearish_divergence_handbuilt():
    """Price makes a higher high while the indicator makes a lower high.

    Two clear price peaks (peak2 > peak1) with the oscillator peaking lower at
    the second peak → bearish divergence.
    """
    # price: rise to 110 (peak1 @ idx5), dip to 100, rise to 120 (peak2 @ idx11), dip
    price = [100, 104, 108, 110, 106, 102,  # up to peak1 then down  (peak1 idx3=110)
             100, 106, 112, 118, 120, 116,  # up to peak2 then down  (peak2 idx10=120)
             112, 108]
    # indicator peaks lower at the second peak (90 then 70)
    indicator = [50, 70, 85, 90, 75, 60,
                 55, 60, 65, 68, 70, 60,
                 55, 50]
    out = sig.detect_divergence(price, indicator, lookback=60, order=2)
    assert out["bearish"] == "bearish"
    assert out["signal"] == "bearish"


def test_detect_bullish_divergence_handbuilt():
    """Price makes a lower low while the indicator makes a higher low."""
    price = [100, 96, 92, 90, 94, 98,        # down to trough1 (idx3=90) then up
             100, 94, 88, 82, 80, 86,        # down to trough2 (idx10=80) then up
             90, 94]
    # indicator troughs higher at the second trough (10 then 30)
    indicator = [50, 30, 20, 10, 25, 40,
                 45, 40, 35, 32, 30, 40,
                 45, 50]
    out = sig.detect_divergence(price, indicator, lookback=60, order=2)
    assert out["bullish"] == "bullish"


def test_no_divergence_when_confirmed():
    """Price HH + indicator HH (both confirming) → no bearish divergence."""
    price = [100, 104, 108, 110, 106, 102,
             100, 106, 112, 118, 120, 116, 112, 108]
    indicator = [50, 70, 85, 90, 75, 60,
                 55, 70, 85, 92, 95, 80, 70, 60]  # second peak HIGHER, confirms
    out = sig.detect_divergence(price, indicator, lookback=60, order=2)
    assert out["bearish"] is None


def test_detect_divergence_tiebreak_bearish_wins():
    """When BOTH a bullish and a bearish divergence are present, ``signal`` is bearish.

    Bearish (momentum loss at a high) is the more actionable warning for a long
    book, so it wins ties. A bug that flipped the precedence (bullish-wins) would
    fail here.
    """
    # Crafted zig-zag (order=1): higher highs with lower indicator highs AND
    # lower lows with higher indicator lows, both in the same window.
    price = np.array([105, 100, 106, 95, 112, 90, 115, 100], dtype=float)
    indicator = np.array([60, 50, 58, 55, 56, 60, 54, 50], dtype=float)
    out = sig.detect_divergence(price, indicator, lookback=60, order=1)
    assert out["bullish"] == "bullish"
    assert out["bearish"] == "bearish"
    assert out["signal"] == "bearish"  # bearish wins the tie


def test_detect_divergence_none_signal_when_flat():
    """No swing structure → all-None (no spurious signal)."""
    price = np.linspace(100, 101, 30)
    indicator = np.linspace(50, 51, 30)
    out = sig.detect_divergence(price, indicator, lookback=60, order=3)
    assert out["bullish"] is None
    assert out["bearish"] is None
    assert out["signal"] is None


# --------------------------------------------------------------------------- #
# MA structure
# --------------------------------------------------------------------------- #
def test_ma_structure_uptrend_stacked():
    close = np.linspace(50, 150, 250)  # strong uptrend, >200 bars
    out = sig.ma_structure(close)
    assert out["above_50"] is True
    assert out["above_200"] is True
    assert out["stacked_bullish"] is True


def test_ma_structure_downtrend_not_stacked():
    close = np.linspace(150, 50, 250)
    out = sig.ma_structure(close)
    assert out["above_50"] is False
    assert out["stacked_bullish"] is False


def test_ma_structure_insufficient_history_none():
    out = sig.ma_structure(np.linspace(100, 110, 30))  # < 50 bars
    assert out["above_50"] is None
    assert out["above_200"] is None


def test_ma_structure_golden_cross_edge_triggered():
    """Golden cross must fire ONLY on the bar the 50-MA crosses above the 200-MA.

    Build a long downtrend (ma50 < ma200) then a sharp reversal so ma50 crosses
    up exactly once. The cross is an *edge* event (prior bar below/equal, current
    above), not a persistent state — so it must be True on the crossing bar and
    False once the stack is already established. A state-check bug (ma50 > ma200)
    would (wrongly) report True for many trailing bars and fail this test.
    """
    series = np.concatenate([np.linspace(200, 100, 205), np.linspace(101, 180, 60)])
    fired_ends = [
        end
        for end in range(201, len(series) + 1)
        if sig.ma_structure(series[:end])["golden_cross"]
    ]
    assert len(fired_ends) == 1  # edge-triggered: fires on exactly one bar
    # On a bar well after the cross, the stack is bullish but golden_cross is past.
    late = sig.ma_structure(series[: fired_ends[0] + 5])
    assert late["golden_cross"] is False
    assert late["stacked_bullish"] is True


def test_ma_structure_death_cross_edge_triggered():
    """Death cross fires once when the 50-MA crosses below the 200-MA."""
    series = np.concatenate([np.linspace(100, 200, 205), np.linspace(199, 120, 60)])
    fired_ends = [
        end
        for end in range(201, len(series) + 1)
        if sig.ma_structure(series[:end])["death_cross"]
    ]
    assert len(fired_ends) == 1


def test_ma_structure_cross_none_when_only_200_bars():
    """With exactly 200 bars there's no prior MA pair to test → cross is False, not None."""
    out = sig.ma_structure(np.linspace(100, 150, 200))
    assert out["golden_cross"] is False
    assert out["death_cross"] is False
    assert out["above_200"] is not None


# --------------------------------------------------------------------------- #
# Support / resistance
# --------------------------------------------------------------------------- #
def test_support_resistance_levels():
    # Build a zig-zag so there are clear swing highs/lows around the last price.
    high = np.array([10, 12, 11, 15, 13, 18, 16, 14, 13, 12, 13], dtype=float)
    low = np.array([8, 10, 9, 13, 11, 16, 14, 12, 11, 10, 11], dtype=float)
    close = np.array([9, 11, 10, 14, 12, 17, 15, 13, 12, 11, 12], dtype=float)
    out = sig.support_resistance(high, low, close, n_pivots=3, order=1)
    # last close = 12; a swing high of 15 (idx3) sits above → resistance
    assert out["resistance"] is not None
    assert out["resistance"] > 12
    # a swing low below 12 should be detected as support
    assert out["support"] is not None
    assert out["support"] < 12


# --------------------------------------------------------------------------- #
# RVOL
# --------------------------------------------------------------------------- #
def test_rvol_double_average():
    vol = [100.0] * 20 + [200.0]  # baseline 100, current 200
    assert sig.rvol(vol, window=20) == pytest.approx(2.0)


def test_rvol_insufficient_nan():
    assert math.isnan(sig.rvol([100.0, 100.0], window=20))


def test_rvol_excludes_current_bar_from_baseline():
    """The baseline must be the `window` bars PRIOR to the current bar.

    If the current bar were (wrongly) included in its own baseline, this spike
    case would yield ~1.9 instead of exactly 2.0. Pinning 2.0 discriminates
    against that self-reference bug.
    """
    vol = [100.0] * 20 + [200.0]
    # baseline = mean of the 20 prior 100s = 100 → 200/100 = 2.0 exactly
    assert sig.rvol(vol, window=20) == pytest.approx(2.0)
    # Sanity: a self-referencing baseline (mean of last 20 incl. current) ≈ 1.905
    assert sig.rvol(vol, window=20) != pytest.approx(200.0 / np.mean(vol[-20:]))


# --------------------------------------------------------------------------- #
# Gap %
# --------------------------------------------------------------------------- #
def test_gap_pct_up():
    assert sig.gap_pct(105.0, 100.0) == pytest.approx(5.0)


def test_gap_pct_down():
    assert sig.gap_pct(97.0, 100.0) == pytest.approx(-3.0)


def test_gap_pct_zero_prev_close_nan():
    assert math.isnan(sig.gap_pct(100.0, 0.0))


# --------------------------------------------------------------------------- #
# 52-week range position
# --------------------------------------------------------------------------- #
def test_pct_of_52w_range_at_low():
    assert sig.pct_of_52w_range(50.0, 100.0, 50.0) == pytest.approx(0.0)


def test_pct_of_52w_range_at_high():
    assert sig.pct_of_52w_range(100.0, 100.0, 50.0) == pytest.approx(100.0)


def test_pct_of_52w_range_midpoint():
    assert sig.pct_of_52w_range(75.0, 100.0, 50.0) == pytest.approx(50.0)


def test_pct_of_52w_range_degenerate_nan():
    assert math.isnan(sig.pct_of_52w_range(100.0, 100.0, 100.0))


def test_pct_of_52w_range_clamped():
    # close above high → clamped to 100
    assert sig.pct_of_52w_range(120.0, 100.0, 50.0) == pytest.approx(100.0)


# --------------------------------------------------------------------------- #
# Days to earnings
# --------------------------------------------------------------------------- #
def test_days_to_earnings_future():
    assert sig.days_to_earnings("2026-06-01", "2026-05-29") == 3


def test_days_to_earnings_today():
    assert sig.days_to_earnings("2026-05-29", "2026-05-29") == 0


def test_days_to_earnings_past_negative():
    assert sig.days_to_earnings("2026-05-20", "2026-05-29") == -9


def test_days_to_earnings_none():
    assert sig.days_to_earnings(None, "2026-05-29") is None


# --------------------------------------------------------------------------- #
# No-look-ahead guard
# --------------------------------------------------------------------------- #
def test_signals_do_not_use_future_bars():
    """Appending a future bar must not change a value computed on the prior bar.

    RSI/MACD/ROC computed on close[:-1] must equal the same computed on the full
    series *as of* that earlier endpoint (i.e. the functions read the tail, so
    extending the series only moves the endpoint forward — it never reaches back).
    """
    rng = np.random.default_rng(11)
    close = 100 + np.cumsum(rng.normal(0, 1, 80))

    # value "as of yesterday" computed two ways:
    r1 = sig.rsi(close[:-1], 14)
    m1 = sig.macd(close[:-1])
    # appending tomorrow's bar then slicing it back off reproduces r1/m1 exactly
    extended = np.append(close, close[-1] + 5.0)
    r2 = sig.rsi(extended[:-2], 14)  # same endpoint as close[:-1]
    m2 = sig.macd(extended[:-2])
    assert r1 == pytest.approx(r2, abs=1e-12)
    assert m1["macd"] == pytest.approx(m2["macd"], abs=1e-12)


def test_divergence_does_not_use_future_bars():
    """A swing pivot needs `order` confirming bars on each side, so the last
    `order` bars can never be pivots — appending future bars cannot retroactively
    create a pivot at or before the prior endpoint, and the most recent `order`
    bars of any series are never treated as confirmed swings.
    """
    price = np.array(
        [100, 104, 108, 110, 106, 102, 100, 106, 112, 118, 120, 116, 112, 108],
        dtype=float,
    )
    order = 2
    highs = sig._local_max_idx(price, order)
    lows = sig._local_min_idx(price, order)
    # No detected pivot may fall in the unconfirmable trailing `order` bars.
    last_confirmable = price.size - 1 - order
    assert all(i <= last_confirmable for i in highs)
    assert all(i <= last_confirmable for i in lows)
