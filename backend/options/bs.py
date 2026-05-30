"""
Black-Scholes pricing, Greeks, implied-volatility solver and expected move.

This is the Python mirror of the client-side math core in the Options
Strategist tab. The frontend prices the interactive payoff lab; the backend
uses these same formulas to derive ATM implied vol from market quotes and to
compute expected moves per expiration (the "timeframe-aware" inputs).

All inputs are in calendar-year terms: T is years to expiry, sigma is annual
volatility (e.g. 0.30 = 30%), r is the annual risk-free rate (e.g. 0.045).
"""

from __future__ import annotations

import math
from typing import Dict, Literal

OptType = Literal["call", "put"]

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _norm_cdf(x: float) -> float:
    # Abramowitz & Stegun 7.1.26 — matches the JS normCDF in the frontend so
    # client and server agree to ~1e-7.
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422804014327 * math.exp(-0.5 * x * x)
    p = d * t * (
        0.31938153
        + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429)))
    )
    return 1.0 - p if x > 0 else p


def price_and_greeks(
    S: float, K: float, T: float, r: float, sigma: float, opt_type: OptType
) -> Dict[str, float]:
    """Black-Scholes price + per-share Greeks.

    Greeks are normalized the same way as the frontend:
      - vega:  per 1 volatility point (1%)
      - theta: per calendar day
    """
    if T <= 1e-9 or sigma <= 0:
        intrinsic = max(S - K, 0.0) if opt_type == "call" else max(K - S, 0.0)
        if opt_type == "call":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return {"price": intrinsic, "delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    sq = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sq)
    d2 = d1 - sigma * sq
    nd1 = _norm_pdf(d1)
    disc = math.exp(-r * T)

    if opt_type == "call":
        price = S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (-S * nd1 * sigma) / (2.0 * sq) - r * K * disc * _norm_cdf(d2)
    else:
        price = K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (-S * nd1 * sigma) / (2.0 * sq) + r * K * disc * _norm_cdf(-d2)

    return {
        "price": price,
        "delta": delta,
        "gamma": nd1 / (S * sigma * sq),
        "vega": (S * nd1 * sq) / 100.0,
        "theta": theta / 365.0,
    }


def price(S: float, K: float, T: float, r: float, sigma: float, opt_type: OptType) -> float:
    return price_and_greeks(S, K, T, r, sigma, opt_type)["price"]


def implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    opt_type: OptType,
    *,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-5,
    max_iter: int = 100,
) -> float:
    """Solve for implied volatility by bisection.

    Returns 0.0 when the price is below intrinsic / un-invertible. Bisection is
    used (not Newton) for robustness across the deep ITM/OTM wings where vega
    collapses and Newton diverges.
    """
    if market_price <= 0 or T <= 0:
        return 0.0

    disc = math.exp(-r * T)
    intrinsic = max(S - K * disc, 0.0) if opt_type == "call" else max(K * disc - S, 0.0)
    if market_price < intrinsic - tol:
        return 0.0

    def f(sig: float) -> float:
        return price(S, K, T, r, sig, opt_type) - market_price

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        # Price outside the model's achievable range for [lo, hi].
        return 0.0

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        fm = f(mid)
        if abs(fm) < tol:
            return mid
        if f_lo * fm < 0:
            b = mid
        else:
            a, f_lo = mid, fm
    return 0.5 * (a + b)


def expected_move(S: float, sigma: float, dte_days: float) -> float:
    """One standard-deviation expected move in price over `dte_days`.

    move = S * sigma * sqrt(T). The ±1σ range (≈68% of outcomes under the
    lognormal-ish assumption) is S ± expected_move — the basis for choosing
    strikes that sit inside or outside the anticipated range.
    """
    if S <= 0 or sigma <= 0 or dte_days <= 0:
        return 0.0
    return S * sigma * math.sqrt(dte_days / 365.0)
