"""Hand-checked unit tests for backend/options/bs.py.

Pins the Black-Scholes formulas against known reference values and identities
(put-call parity, round-tripping implied vol) so the math agrees with the
client-side engine in the Options Strategist tab.
"""

import math

import pytest

from options import bs


# --------------------------------------------------------------------------- #
# Pricing — reference values
# --------------------------------------------------------------------------- #
def test_atm_call_known_value():
    """S=100, K=100, T=1, r=5%, sigma=20% -> call ≈ 10.4506 (textbook value)."""
    p = bs.price(100, 100, 1.0, 0.05, 0.20, "call")
    assert p == pytest.approx(10.4506, abs=1e-3)


def test_atm_put_known_value():
    """Same inputs -> put ≈ 5.5735."""
    p = bs.price(100, 100, 1.0, 0.05, 0.20, "put")
    assert p == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    """C - P == S - K*exp(-rT) for any strike."""
    S, K, T, r, sig = 100, 90, 0.5, 0.04, 0.35
    c = bs.price(S, K, T, r, sig, "call")
    p = bs.price(S, K, T, r, sig, "put")
    assert (c - p) == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)


# --------------------------------------------------------------------------- #
# Greeks
# --------------------------------------------------------------------------- #
def test_atm_call_delta_near_half():
    g = bs.price_and_greeks(100, 100, 1.0, 0.05, 0.20, "call")
    # ATM call delta is a little above 0.5 with positive carry.
    assert 0.5 < g["delta"] < 0.65


def test_call_put_delta_relationship():
    """call_delta - put_delta == 1 (no-dividend BS)."""
    c = bs.price_and_greeks(100, 105, 0.75, 0.03, 0.25, "call")
    p = bs.price_and_greeks(100, 105, 0.75, 0.03, 0.25, "put")
    assert (c["delta"] - p["delta"]) == pytest.approx(1.0, abs=1e-6)


def test_long_option_theta_negative():
    g = bs.price_and_greeks(100, 100, 0.25, 0.05, 0.30, "call")
    assert g["theta"] < 0
    assert g["vega"] > 0
    assert g["gamma"] > 0


def test_expiry_returns_intrinsic():
    g = bs.price_and_greeks(110, 100, 0.0, 0.05, 0.20, "call")
    assert g["price"] == pytest.approx(10.0)
    assert g["gamma"] == 0.0 and g["theta"] == 0.0 and g["vega"] == 0.0


# --------------------------------------------------------------------------- #
# Implied volatility — round trip
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("opt_type", ["call", "put"])
@pytest.mark.parametrize("sigma", [0.12, 0.25, 0.60, 1.10])
def test_implied_vol_round_trip(opt_type, sigma):
    S, K, T, r = 100, 105, 0.5, 0.04
    mkt = bs.price(S, K, T, r, sigma, opt_type)
    recovered = bs.implied_vol(mkt, S, K, T, r, opt_type)
    assert recovered == pytest.approx(sigma, abs=1e-3)


def test_implied_vol_below_intrinsic_returns_zero():
    # A price under intrinsic is un-invertible -> 0.0, not an exception.
    assert bs.implied_vol(0.01, 150, 100, 0.5, 0.04, "call") == 0.0


# --------------------------------------------------------------------------- #
# Expected move
# --------------------------------------------------------------------------- #
def test_expected_move_scales_with_sqrt_time():
    m30 = bs.expected_move(100, 0.30, 30)
    m120 = bs.expected_move(100, 0.30, 120)
    # 4x the days -> 2x the move.
    assert m120 == pytest.approx(2 * m30, rel=1e-6)


def test_expected_move_one_year_atm():
    # Over 1y, ±1σ move ≈ S*sigma.
    assert bs.expected_move(100, 0.30, 365) == pytest.approx(30.0, abs=1e-2)
