"""Hand-calculated unit tests for backend/analytics/position.py.

Each assertion uses inputs whose expected output is computed by hand (or by an
independent reference implementation in the test) so the test pins the formula,
not the implementation.
"""

import math

import numpy as np
import pytest

from analytics import position as pos


# --------------------------------------------------------------------------- #
# ATR (Wilder)
# --------------------------------------------------------------------------- #
def test_atr_constant_true_range():
    """If every bar has the same true range, ATR equals that range exactly.

    Construct 20 bars where high-low = 2 and there are no gaps (close sits
    inside the bar), so TR == 2 for every bar. Wilder smoothing of a constant
    is that constant.
    """
    n = 20
    close = np.full(n, 100.0)
    high = close + 1.0  # high-low = 2, |high-prev_close| = 1, |low-prev_close| = 1
    low = close - 1.0
    result = pos.atr(high, low, close, period=14)
    assert result == pytest.approx(2.0, abs=1e-9)


def test_atr_matches_reference_wilder():
    """ATR on a known OHLC series matches an independent Wilder reference."""
    high = np.array([10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20, 21], dtype=float)
    low = np.array([9, 10, 10, 9, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 19], dtype=float)
    close = np.array([9.5, 10.5, 11, 10, 12.5, 13, 12, 14.5, 15, 14, 16.5, 17, 16, 18.5, 19, 20.5], dtype=float)
    period = 14

    # Independent reference Wilder computation
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for t in range(1, n):
        tr[t] = max(
            high[t] - low[t],
            abs(high[t] - close[t - 1]),
            abs(low[t] - close[t - 1]),
        )
    ref = float(np.mean(tr[1 : period + 1]))  # seed
    for t in range(period + 1, n):
        ref = (ref * (period - 1) + tr[t]) / period

    assert pos.atr(high, low, close, period=period) == pytest.approx(ref, rel=1e-12)


def test_atr_seed_excludes_first_bar_pseudo_tr():
    """Discriminating Wilder test: the high-low-only TR of bar 0 must NOT be
    in the seed window. Bar 0 here has a huge range (30) while every real TR
    is small, so an off-by-one seed (including tr[0]) would inflate the result.

    The expected value 2.46428571... is a hand-pinned *constant*, computed once
    from the standard Wilder definition (seed = mean of the first `period` TRs
    that use a prior close, then recursive smoothing). It does NOT re-derive the
    seed slice from the implementation, so it catches off-by-one seeding.
    """
    high = np.array([30, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20, 21], dtype=float)
    low = np.array([0, 10, 10, 9, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 19], dtype=float)
    close = np.array([15, 10.5, 11, 10, 12.5, 13, 12, 14.5, 15, 14, 16.5, 17, 16, 18.5, 19, 20.5], dtype=float)
    # If the seed wrongly included tr[0]=30 the answer would be ~4.1556.
    assert pos.atr(high, low, close, period=14) == pytest.approx(2.46428571428571, rel=1e-12)


def test_atr_insufficient_data_is_nan():
    high = np.arange(1, 6, dtype=float) + 1
    low = np.arange(1, 6, dtype=float) - 1
    close = np.arange(1, 6, dtype=float)
    assert math.isnan(pos.atr(high, low, close, period=14))


def test_atr_length_mismatch_raises():
    with pytest.raises(ValueError):
        pos.atr([1, 2, 3], [1, 2], [1, 2, 3], period=2)


# --------------------------------------------------------------------------- #
# ATR levels
# --------------------------------------------------------------------------- #
def test_atr_levels_long():
    lv = pos.atr_levels(entry=100.0, atr=2.0, stop_mult=2.0, target_mult=3.0, direction="long")
    assert lv["stop"] == pytest.approx(96.0)  # 100 - 2*2
    assert lv["target"] == pytest.approx(106.0)  # 100 + 3*2


def test_atr_levels_short_mirrors():
    lv = pos.atr_levels(entry=100.0, atr=2.0, stop_mult=2.0, target_mult=3.0, direction="short")
    assert lv["stop"] == pytest.approx(104.0)  # 100 + 2*2
    assert lv["target"] == pytest.approx(94.0)  # 100 - 3*2


def test_atr_levels_bad_direction():
    with pytest.raises(ValueError):
        pos.atr_levels(100.0, 2.0, direction="sideways")


# --------------------------------------------------------------------------- #
# R-multiple
# --------------------------------------------------------------------------- #
def test_r_multiple_plus_one_r_long():
    """Long: entry 100, stop 90 -> risk 10. current 110 == +1R."""
    assert pos.r_multiple(current=110.0, entry=100.0, stop=90.0) == pytest.approx(1.0)


def test_r_multiple_at_stop_is_minus_one():
    assert pos.r_multiple(current=90.0, entry=100.0, stop=90.0) == pytest.approx(-1.0)


def test_r_multiple_two_r_long():
    assert pos.r_multiple(current=120.0, entry=100.0, stop=90.0) == pytest.approx(2.0)


def test_r_multiple_short_favorable_is_positive():
    """Short: entry 100, stop 110 -> risk 10. price down to 80 == +2R."""
    assert pos.r_multiple(current=80.0, entry=100.0, stop=110.0) == pytest.approx(2.0)
    # and exactly +1R one risk-unit below entry
    assert pos.r_multiple(current=90.0, entry=100.0, stop=110.0) == pytest.approx(1.0)


def test_r_multiple_short_at_stop_is_minus_one():
    assert pos.r_multiple(current=110.0, entry=100.0, stop=110.0) == pytest.approx(-1.0)


def test_r_multiple_zero_risk_is_nan():
    assert math.isnan(pos.r_multiple(current=100.0, entry=100.0, stop=100.0))


def test_unrealized_r_is_alias():
    assert pos.unrealized_r(110.0, 100.0, 90.0) == pytest.approx(pos.r_multiple(110.0, 100.0, 90.0))


# --------------------------------------------------------------------------- #
# Distance to stop
# --------------------------------------------------------------------------- #
def test_distance_to_stop_pct():
    assert pos.distance_to_stop_pct(entry=100.0, stop=98.0) == pytest.approx(0.02)
    assert pos.distance_to_stop_pct(entry=100.0, stop=105.0) == pytest.approx(0.05)


def test_distance_to_stop_pct_zero_entry_nan():
    assert math.isnan(pos.distance_to_stop_pct(entry=0.0, stop=5.0))


# --------------------------------------------------------------------------- #
# Position sizing
# --------------------------------------------------------------------------- #
def test_fixed_fractional_sizing_example():
    """$100k account, risk 2% ($2,000), stop $5 away -> 400 shares."""
    shares = pos.position_size_fixed_fractional(
        account_value=100_000.0, risk_pct=0.02, per_share_risk=5.0
    )
    assert shares == pytest.approx(400.0)


def test_fixed_fractional_zero_risk_is_zero():
    assert pos.position_size_fixed_fractional(100_000.0, 0.02, 0.0) == 0.0


# --------------------------------------------------------------------------- #
# Kelly
# --------------------------------------------------------------------------- #
def test_kelly_fraction_known_value():
    """p=0.6, b=2 -> f* = p - q/b = 0.6 - 0.4/2 = 0.4."""
    assert pos.kelly_fraction(win_rate=0.6, win_loss_ratio=2.0) == pytest.approx(0.4)


def test_kelly_even_money_breakeven():
    """p=0.5, b=1 -> f* = 0.5 - 0.5/1 = 0.0 (no edge)."""
    assert pos.kelly_fraction(0.5, 1.0) == pytest.approx(0.0)


def test_kelly_negative_edge():
    """p=0.4, b=1 -> f* = 0.4 - 0.6 = -0.2 (don't bet)."""
    assert pos.kelly_fraction(0.4, 1.0) == pytest.approx(-0.2)


def test_kelly_bad_ratio_nan():
    assert math.isnan(pos.kelly_fraction(0.6, 0.0))


def test_fractional_kelly_quarter():
    assert pos.fractional_kelly(0.4, frac=0.25) == pytest.approx(0.1)


def test_fractional_kelly_default_is_quarter():
    assert pos.fractional_kelly(0.4) == pytest.approx(0.1)


# --------------------------------------------------------------------------- #
# Days held
# --------------------------------------------------------------------------- #
def test_days_held_basic():
    assert pos.days_held("2026-01-01", "2026-01-11") == 10


def test_days_held_same_day_zero():
    assert pos.days_held("2026-01-01", "2026-01-01") == 0


def test_days_held_ignores_time_of_day():
    assert pos.days_held("2026-01-01 09:30", "2026-01-02 16:00") == 1


def test_days_held_never_negative():
    assert pos.days_held("2026-01-10", "2026-01-01") == 0


# --------------------------------------------------------------------------- #
# Position vol / beta (local fallback path)
# --------------------------------------------------------------------------- #
def test_position_vol_matches_formula():
    r = np.array([0.01, -0.02, 0.015, 0.0, -0.005])
    expected = float(np.std(r, ddof=1) * np.sqrt(252))
    assert pos.position_vol(r, periods_per_year=252) == pytest.approx(expected)


def test_position_vol_too_short_nan():
    assert math.isnan(pos.position_vol([0.01]))


def test_position_beta_perfectly_correlated_is_one():
    """Asset == market -> beta = var/var = 1.0."""
    m = np.array([0.01, -0.02, 0.03, -0.01, 0.005])
    assert pos.position_beta(m, m) == pytest.approx(1.0)


def test_position_beta_double_market_is_two():
    """Asset = 2 * market -> beta = cov(2m,m)/var(m) = 2."""
    m = np.array([0.01, -0.02, 0.03, -0.01, 0.005])
    a = 2.0 * m
    assert pos.position_beta(a, m) == pytest.approx(2.0)


def test_position_beta_negative_when_inverse():
    """Asset = -0.5 * market -> beta = cov(-0.5m, m)/var(m) = -0.5.

    Pins the sign of the covariance term (an inverted/hedge asset must yield a
    negative beta), which the correlated/2x cases cannot catch.
    """
    m = np.array([0.01, -0.02, 0.03, -0.01, 0.005])
    a = -0.5 * m
    assert pos.position_beta(a, m) == pytest.approx(-0.5)


def test_position_beta_length_mismatch_raises():
    with pytest.raises(ValueError):
        pos.position_beta([0.01, 0.02], [0.01, 0.02, 0.03])


def test_position_beta_too_short_nan():
    assert math.isnan(pos.position_beta([0.01], [0.01]))
