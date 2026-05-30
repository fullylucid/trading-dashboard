"""PURE tests for the price/momentum backbone (``sector_rotation.market``).

No network. These exercise only the pure compute functions: relative strength,
RS-Ratio / RS-Momentum, RRG quadrant assignment (on synthetic leading / lagging
series), multi-timeframe ROC, OBV / RVOL money-flow proxies, the ETF-level
breadth proxy, and the pure assembler. The IO functions
(``fetch_rotation_ohlcv`` / ``scan_market_rotation``) are NOT exercised here —
they are thin, exception-wrapped adapters over this unit-tested core.
"""

import numpy as np
import pandas as pd
import pytest

from sector_rotation import market as mk


# --------------------------------------------------------------------------- #
# relative_strength
# --------------------------------------------------------------------------- #
def test_relative_strength_basic_ratio():
    rs = mk.relative_strength([100, 110, 120], [100, 100, 100])
    # (sector/benchmark)*100
    assert list(rs.round(4)) == [100.0, 110.0, 120.0]


def test_relative_strength_drops_zero_benchmark():
    rs = mk.relative_strength([100, 110, 120], [100, 0, 50])
    # the zero-benchmark middle point drops out
    assert len(rs) == 2
    assert rs.iloc[0] == pytest.approx(100.0)
    assert rs.iloc[-1] == pytest.approx(240.0)


# --------------------------------------------------------------------------- #
# rs_ratio  (z-score normalization centered at 100)
# --------------------------------------------------------------------------- #
def test_rs_ratio_centers_at_100_and_zscores():
    # Strictly rising RS -> latest point is the max -> above its own mean ->
    # RS-Ratio > 100.
    rs = pd.Series(np.linspace(90, 110, 40))
    ratio = mk.rs_ratio(rs, period=14)
    assert ratio.iloc[-1] > 100.0
    # The math: 100 + (rs - sma)/std on the trailing window.
    window = rs.iloc[-14:]
    expected = 100.0 + (rs.iloc[-1] - window.mean()) / window.std(ddof=0)
    assert ratio.iloc[-1] == pytest.approx(expected)


def test_rs_ratio_flat_series_is_nan():
    # Zero variance -> stddev 0 -> NaN (not inf/crash).
    ratio = mk.rs_ratio(pd.Series([100.0] * 30), period=14)
    assert np.isnan(ratio.iloc[-1])


def test_rs_ratio_requires_period_ge_2():
    with pytest.raises(ValueError):
        mk.rs_ratio(pd.Series([1.0, 2.0, 3.0]), period=1)


# --------------------------------------------------------------------------- #
# rs_momentum
# --------------------------------------------------------------------------- #
def test_rs_momentum_matches_zscored_roc_formula():
    # Verify the exact spec formula rather than asserting a sign on a synthetic
    # curve (the z-score is mean-reverting, so a steady trend does not imply a
    # particular momentum sign). mom_value = ratio/ratio[n ago]-1, then
    # 100 + mom_value / std(mom_value, n).
    rs = pd.Series(np.linspace(90, 115, 60))
    ratio = mk.rs_ratio(rs, period=14)
    mom = mk.rs_momentum(ratio, period=14)
    mom_value = (ratio / ratio.shift(14)) - 1.0
    sd = mom_value.rolling(14).std(ddof=0)
    expected_last = 100.0 + mom_value.iloc[-1] / sd.iloc[-1]
    assert mom.iloc[-1] == pytest.approx(expected_last)


def test_rs_momentum_flat_ratio_is_nan():
    # constant ratio -> zero ROC variance -> NaN (no crash / inf)
    mom = mk.rs_momentum(pd.Series([100.0] * 60), period=14)
    assert np.isnan(mom.iloc[-1])


# --------------------------------------------------------------------------- #
# rrg_quadrant — the core quadrant assignment table
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ratio,mom,expected",
    [
        (104.0, 102.0, mk.LEADING),
        (104.0, 98.0, mk.WEAKENING),
        (96.0, 98.0, mk.LAGGING),
        (96.0, 102.0, mk.IMPROVING),
        # boundary: exactly 100 is treated as the non-leading / non-lagging side
        (100.0, 100.0, mk.LAGGING),
        (101.0, 100.0, mk.WEAKENING),
        (100.0, 101.0, mk.IMPROVING),
        # missing -> NEUTRAL
        (None, 102.0, mk.NEUTRAL),
        (104.0, None, mk.NEUTRAL),
        (float("nan"), 102.0, mk.NEUTRAL),
    ],
)
def test_rrg_quadrant_table(ratio, mom, expected):
    assert mk.rrg_quadrant(ratio, mom) == expected


# --------------------------------------------------------------------------- #
# compute_rrg on synthetic LEADING vs LAGGING series
# --------------------------------------------------------------------------- #
def _leading_sector(n=160):
    """Synthetic sector whose RS lands in the LEADING quadrant vs a flat bench.

    A dip-then-late-recovery shape: RS dips below its mean, then surges in the
    final bars so that at the last bar RS-Ratio > 100 (recent surge is above the
    window mean) AND RS-Momentum > 100 (ROC of the ratio is rising). Hand-tuned
    and asserted below so the wiring (RS -> ratio -> momentum -> quadrant) is
    exercised end-to-end.
    """
    s = np.full(n, 100.0)
    s[-40:-15] = 100.0 - np.linspace(0, 8, 25)
    s[-15:] = s[-16] + np.linspace(0, 10, 15)
    return pd.Series(s)


def _lagging_sector(n=160):
    """Synthetic sector landing in the LAGGING quadrant: a peak-then-rollover."""
    s = np.full(n, 100.0)
    s[-40:-15] = 100.0 + np.linspace(0, 8, 25)
    s[-15:] = s[-16] - np.linspace(0, 10, 15)
    return pd.Series(s)


def test_compute_rrg_synthetic_leading():
    # RS surging up at the end vs a flat benchmark -> RS-Ratio > 100 and
    # RS-Momentum > 100 -> Leading.
    n = 160
    bench = pd.Series([100.0] * n)
    res = mk.compute_rrg(_leading_sector(n), bench, period=14)
    assert res["rs_ratio"] > 100.0
    assert res["rs_momentum"] > 100.0
    assert res["quadrant"] == mk.LEADING


def test_compute_rrg_synthetic_lagging():
    # RS rolling over at the end vs a flat benchmark -> RS-Ratio < 100 and
    # RS-Momentum < 100 -> Lagging.
    n = 160
    bench = pd.Series([100.0] * n)
    res = mk.compute_rrg(_lagging_sector(n), bench, period=14)
    assert res["rs_ratio"] < 100.0
    assert res["rs_momentum"] < 100.0
    assert res["quadrant"] == mk.LAGGING


def test_compute_rrg_too_short_degrades_neutral():
    res = mk.compute_rrg([100, 101, 102], [100, 100, 100], period=14)
    assert res["rs_ratio"] is None
    assert res["rs_momentum"] is None
    assert res["quadrant"] == mk.NEUTRAL


# --------------------------------------------------------------------------- #
# multi-timeframe ROC
# --------------------------------------------------------------------------- #
def test_roc_percent():
    # +10% over 5 bars
    prices = [100, 101, 102, 103, 104, 110]
    assert mk.roc(prices, 5) == pytest.approx(10.0)


def test_roc_insufficient_bars_none():
    assert mk.roc([100, 101], 5) is None


def test_roc_nonpositive_reference_none():
    assert mk.roc([0.0, 1, 2, 3, 4, 5], 5) is None


def test_multi_timeframe_roc_keys_and_values():
    prices = list(np.linspace(100, 200, 80))
    out = mk.multi_timeframe_roc(prices)
    assert set(out) == {"1w", "1m", "3m"}
    # monotonic up series -> every window positive
    assert all(v is not None and v > 0 for v in out.values())


# --------------------------------------------------------------------------- #
# OBV / RVOL money-flow proxies
# --------------------------------------------------------------------------- #
def test_obv_signed_accumulation():
    close = [10, 11, 10, 12]       # up, down, up
    vol = [100, 200, 300, 400]
    obv = mk.on_balance_volume(close, vol)
    # first bar 0, then +200, then -300, then +400 -> cumulative
    assert list(obv) == [0.0, 200.0, -100.0, 300.0]


def test_relative_volume_spike():
    vol = [100] * 19 + [300]       # 20 bars, last = 3x the average-ish
    rvol = mk.relative_volume(vol, window=20)
    # avg over last 20 = (100*19 + 300)/20 = 110 ; 300/110
    assert rvol == pytest.approx(300.0 / 110.0)


def test_relative_volume_insufficient_none():
    assert mk.relative_volume([100, 100], window=20) is None


def test_money_flow_proxies_block():
    close = list(np.linspace(10, 20, 40))   # steadily up -> OBV rising
    vol = [100] * 40
    mf = mk.money_flow_proxies(close, vol, window=20)
    assert mf["obv_rising"] is True
    assert mf["rvol"] == pytest.approx(1.0)
    assert mf["obv"] is not None


# --------------------------------------------------------------------------- #
# breadth proxy
# --------------------------------------------------------------------------- #
def test_breadth_proxy_counts_above_ma():
    up = list(np.linspace(10, 20, 60))      # last close above its 50-MA
    down = list(np.linspace(20, 10, 60))    # last close below its 50-MA
    res = mk.breadth_proxy({"XLK": up, "XLF": down, "XLE": up}, ma_window=50)
    assert res["total"] == 3
    assert res["count_above"] == 2
    assert res["pct_above"] == pytest.approx(2 / 3 * 100.0)
    assert res["per_sector"]["XLK"] is True
    assert res["per_sector"]["XLF"] is False


def test_breadth_proxy_short_series_excluded():
    res = mk.breadth_proxy({"XLK": [1, 2, 3]}, ma_window=50)
    assert res["total"] == 0
    assert res["pct_above"] is None
    assert res["per_sector"]["XLK"] is None


# --------------------------------------------------------------------------- #
# _completed_close — the no-look-ahead contract (drops the in-progress tail bar)
# --------------------------------------------------------------------------- #
def test_completed_close_drops_in_progress_tail_bar():
    # DISCRIMINATING no-look-ahead audit: fetch_ohlcv returns bars through "now",
    # so the most-recent bar can be partial during market hours. The IO adapter
    # MUST drop it before any compute. A regression that kept the tail bar would
    # leak today's (in-progress) price into the signals.
    df = pd.DataFrame(
        {
            "Adj Close": [10.0, 11.0, 12.0, 99.0],  # 99.0 == today's partial bar
            "Close": [10.0, 11.0, 12.0, 99.0],
            "Volume": [100.0, 100.0, 100.0, 5.0],
        }
    )
    series = mk._completed_close(df, "Adj Close")
    assert series is not None
    # The in-progress tail (99.0) must be gone; last completed bar is 12.0.
    assert list(series) == [10.0, 11.0, 12.0]
    assert 99.0 not in list(series)


def test_completed_close_falls_back_close_when_no_adj_close():
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0, 4.0]})
    series = mk._completed_close(df, "Adj Close")
    assert list(series) == [1.0, 2.0, 3.0]  # tail dropped, Close fallback used


def test_completed_close_too_short_returns_none():
    # After dropping the tail bar there must be >= 2 completed bars.
    df = pd.DataFrame({"Adj Close": [1.0, 2.0]})
    assert mk._completed_close(df, "Adj Close") is None
    assert mk._completed_close(None, "Adj Close") is None


# --------------------------------------------------------------------------- #
# build_rotation_block (pure assembler)
# --------------------------------------------------------------------------- #
def test_build_rotation_block_shape_and_degradation():
    n = 160
    bench = pd.Series([100.0] * n)
    leading = _leading_sector(n)
    sector_series = {
        "XLK": {"close": leading, "volume": pd.Series([100.0] * n)},
        "XLF": {"close": [1, 2, 3], "volume": [1, 1, 1]},  # too short -> NEUTRAL
    }
    block = mk.build_rotation_block(sector_series, bench)
    assert block["benchmark"] == mk.BENCHMARK
    assert block["sectors"]["XLK"]["sector"] == "Information Technology"
    assert block["sectors"]["XLK"]["quadrant"] == mk.LEADING
    # too-short series degrades, does not raise
    assert block["sectors"]["XLF"]["quadrant"] == mk.NEUTRAL
    assert block["sectors"]["XLF"]["rs_ratio"] is None
    assert "roc" in block["sectors"]["XLK"]
    assert "money_flow" in block["sectors"]["XLK"]
    assert "pct_above" in block["breadth"]


def test_build_rotation_block_never_raises_on_garbage():
    # totally malformed series must not raise
    block = mk.build_rotation_block(
        {"XLK": {"close": ["a", "b"], "volume": None}},
        pd.Series([100.0] * 50),
    )
    assert block["sectors"]["XLK"]["quadrant"] == mk.NEUTRAL
