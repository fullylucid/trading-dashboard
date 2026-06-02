"""
Black-Scholes option Greeks + probabilities — pure stdlib (no numpy/scipy).

yfinance gives us price + implied vol but not Greeks; we compute them from IV, spot,
strike, time, and the risk-free rate. Good enough for strategy formulation; for native
real-time Greeks a paid vendor (Tradier/ORATS) would drop in as the chain source.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SQRT2PI = math.sqrt(2 * math.pi)


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float      # per calendar day
    vega: float       # per 1 vol point (1%)
    rho: float        # per 1% rate move
    prob_itm: float   # risk-neutral P(expire ITM)


def compute(
    spot: float, strike: float, t_years: float, iv: float,
    rate: float = 0.044, is_call: bool = True, div_yield: float = 0.0,
) -> Greeks:
    """Black-Scholes-Merton Greeks. t_years = days_to_exp/365; iv as a fraction (0.45 = 45%)."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or iv <= 0:
        return Greeks(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    s, k, t, r, q = spot, strike, t_years, rate, div_yield
    vol_t = iv * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * iv * iv) * t) / vol_t
    d2 = d1 - vol_t
    disc = math.exp(-r * t)
    dy = math.exp(-q * t)
    nd1, nd2 = _cdf(d1), _cdf(d2)
    pdf_d1 = _pdf(d1)

    gamma = dy * pdf_d1 / (s * vol_t)
    vega = s * dy * pdf_d1 * math.sqrt(t) / 100.0
    if is_call:
        delta = dy * nd1
        theta = (-(s * dy * pdf_d1 * iv) / (2 * math.sqrt(t))
                 - r * k * disc * nd2 + q * s * dy * nd1) / 365.0
        rho = k * t * disc * nd2 / 100.0
        prob_itm = nd2
    else:
        delta = dy * (nd1 - 1.0)
        theta = (-(s * dy * pdf_d1 * iv) / (2 * math.sqrt(t))
                 + r * k * disc * _cdf(-d2) - q * s * dy * _cdf(-d1)) / 365.0
        rho = -k * t * disc * _cdf(-d2) / 100.0
        prob_itm = _cdf(-d2)
    return Greeks(delta, gamma, theta, vega, rho, prob_itm)
