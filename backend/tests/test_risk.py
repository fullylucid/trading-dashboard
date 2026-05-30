"""Known-input unit tests for backend/analytics/risk.py.

Pure-function tests: every assertion uses an analytically known answer so a
regression in the math is caught, not just a crash.
"""

import math

import numpy as np
import pandas as pd
import pytest

from analytics import risk


# ---------------------------------------------------------------------------
# beta
# ---------------------------------------------------------------------------
def test_beta_of_2x_is_2():
    rng = np.random.default_rng(0)
    market = rng.normal(0.0, 0.01, 500)
    asset = 2.0 * market
    assert risk.beta(asset, market) == pytest.approx(2.0, rel=1e-9)


def test_beta_of_negative_half_x():
    rng = np.random.default_rng(1)
    market = rng.normal(0.0, 0.02, 300)
    asset = -0.5 * market
    assert risk.beta(asset, market) == pytest.approx(-0.5, rel=1e-9)


def test_beta_zero_market_variance_is_nan():
    market = np.zeros(50)
    asset = np.ones(50)
    assert math.isnan(risk.beta(asset, market))


def test_beta_length_mismatch_raises():
    with pytest.raises(ValueError):
        risk.beta([0.1, 0.2, 0.3], [0.1, 0.2])


# ---------------------------------------------------------------------------
# annualized volatility
# ---------------------------------------------------------------------------
def test_annualized_volatility_known():
    # std (ddof=1) of [0.01, -0.01, 0.01, -0.01] alternating.
    r = np.array([0.01, -0.01, 0.01, -0.01])
    expected = np.std(r, ddof=1) * np.sqrt(252)
    assert risk.annualized_volatility(r) == pytest.approx(expected)


def test_annualized_volatility_periods_scaling():
    r = np.array([0.02, -0.01, 0.015, -0.005, 0.01])
    daily = risk.annualized_volatility(r, periods=252)
    monthly = risk.annualized_volatility(r, periods=12)
    assert daily / monthly == pytest.approx(np.sqrt(252 / 12))


# ---------------------------------------------------------------------------
# portfolio volatility
# ---------------------------------------------------------------------------
def test_portfolio_volatility_full_cov():
    # Two assets, var 0.04 each, covariance 0.0, equal weights.
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    w = np.array([0.5, 0.5])
    # variance = 0.25*0.04 + 0.25*0.04 = 0.02 -> sigma = sqrt(0.02)
    assert risk.portfolio_volatility(w, cov) == pytest.approx(math.sqrt(0.02))


def test_portfolio_volatility_perfect_correlation_equals_weighted_vol():
    sigma1, sigma2 = 0.1, 0.2
    cov = np.array([[sigma1**2, sigma1 * sigma2], [sigma1 * sigma2, sigma2**2]])
    w = np.array([0.5, 0.5])
    # perfectly correlated -> portfolio vol == weighted average of vols
    assert risk.portfolio_volatility(w, cov) == pytest.approx(0.5 * sigma1 + 0.5 * sigma2)


def test_portfolio_volatility_diag_matches_full_when_uncorrelated():
    variances = np.array([0.04, 0.09])
    w = np.array([0.6, 0.4])
    cov = np.diag(variances)
    assert risk.portfolio_volatility_diag(w, variances) == pytest.approx(
        risk.portfolio_volatility(w, cov)
    )


def test_portfolio_volatility_non_square_raises():
    with pytest.raises(ValueError):
        risk.portfolio_volatility([0.5, 0.5], [[0.04, 0.0, 0.0]])


# ---------------------------------------------------------------------------
# value at risk
# ---------------------------------------------------------------------------
def test_var_historical_percentile():
    # returns 0..-99 (as fractions); 5th percentile of -0..-99.
    returns = -np.arange(100) / 100.0  # 0.0, -0.01, ..., -0.99
    out = risk.value_at_risk(returns, conf=0.95)
    expected_q = np.percentile(returns, 5.0)
    assert out["historical"] == pytest.approx(-expected_q)


def test_var_parametric_gaussian():
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0, 0.01, 100_000)
    out = risk.value_at_risk(returns, conf=0.95)
    # z_0.95 ~= 1.6449; mu ~ 0, sigma ~ 0.01 -> parametric VaR ~ 0.01645
    assert out["parametric"] == pytest.approx(1.6449 * 0.01, abs=5e-4)


def test_var_norm_ppf_known_values():
    assert risk._norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-4)
    assert risk._norm_ppf(0.95) == pytest.approx(1.644854, abs=1e-4)
    assert risk._norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_var_bad_conf_raises():
    with pytest.raises(ValueError):
        risk.value_at_risk([0.01, -0.02], conf=1.5)


# ---------------------------------------------------------------------------
# max drawdown
# ---------------------------------------------------------------------------
def test_max_drawdown_known_curve():
    # peak 100 -> trough 80 == -20% drawdown, then recovers.
    curve = np.array([100, 110, 120, 90, 96, 130])
    # running peak at the 90 point is 120 -> 90/120 - 1 = -0.25
    assert risk.max_drawdown(curve) == pytest.approx(-0.25)


def test_max_drawdown_monotonic_is_zero():
    curve = np.array([1.0, 1.1, 1.2, 1.3])
    assert risk.max_drawdown(curve) == pytest.approx(0.0)


def test_max_drawdown_simple_halving():
    curve = np.array([100.0, 50.0])
    assert risk.max_drawdown(curve) == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# sharpe / sortino
# ---------------------------------------------------------------------------
def test_sharpe_zero_rf_known():
    r = np.array([0.01, 0.02, -0.01, 0.03, 0.0])
    mean = np.mean(r)
    sd = np.std(r, ddof=1)
    expected = mean / sd * np.sqrt(252)
    assert risk.sharpe(r, rf_annual=0.0) == pytest.approx(expected)


def test_sharpe_zero_vol_is_nan():
    r = np.array([0.001, 0.001, 0.001])  # constant -> zero excess vol
    assert math.isnan(risk.sharpe(r, rf_annual=0.0))


def test_sortino_all_positive_is_inf():
    r = np.array([0.01, 0.02, 0.03])
    assert math.isinf(risk.sortino(r, mar=0.0))


def test_sortino_known_downside():
    r = np.array([0.02, -0.01, 0.03, -0.02])
    excess = r  # mar=0
    downside = np.minimum(excess, 0.0)
    dd = np.sqrt(np.mean(downside ** 2))
    expected = np.mean(excess) / dd * np.sqrt(252)
    assert risk.sortino(r, mar=0.0) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# correlation matrix
# ---------------------------------------------------------------------------
def test_correlation_matrix_perfect_and_anti():
    base = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    df = pd.DataFrame({"A": base, "B": 2 * base, "C": -base})
    corr = risk.correlation_matrix(df)
    assert corr.loc["A", "A"] == pytest.approx(1.0)
    assert corr.loc["A", "B"] == pytest.approx(1.0)
    assert corr.loc["A", "C"] == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# concentration: HHI / ENS
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n", [1, 2, 4, 10])
def test_hhi_equal_weights_is_one_over_n(n):
    w = np.ones(n) / n
    assert risk.hhi(w) == pytest.approx(1.0 / n)


def test_hhi_normalizes_unnormalized_weights():
    # equal but unnormalized (sum=8) -> still 1/4
    assert risk.hhi([2, 2, 2, 2]) == pytest.approx(0.25)


def test_hhi_fully_concentrated_is_one():
    assert risk.hhi([1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_effective_number_equal_weights():
    w = np.ones(5) / 5
    assert risk.effective_number(w) == pytest.approx(5.0)


def test_hhi_zero_total_is_nan():
    assert math.isnan(risk.hhi([0.0, 0.0]))


# ---------------------------------------------------------------------------
# sector exposure
# ---------------------------------------------------------------------------
def test_sector_exposure_aggregates_and_sorts():
    positions = [
        {"sector": "Tech", "weight": 0.4},
        {"sector": "Tech", "weight": 0.2},
        {"sector": "Energy", "weight": 0.4},
    ]
    out = risk.sector_exposure(positions)
    assert out == {"Tech": pytest.approx(0.6), "Energy": pytest.approx(0.4)}
    # sorted descending: Tech first
    assert list(out.keys())[0] == "Tech"


def test_sector_exposure_missing_sector_is_unknown():
    out = risk.sector_exposure([{"weight": 0.5}, {"sector": None, "weight": 0.5}])
    assert out["Unknown"] == pytest.approx(1.0)
