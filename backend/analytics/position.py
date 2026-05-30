"""Per-position analytics: pure, deterministic, dependency-light functions.

All functions take data IN (numpy arrays / pandas Series / scalars) and return
numbers or dicts. NO network or disk I/O is performed here — the caller is
responsible for fetching and cleaning data.

Conventions
-----------
- **Adjusted close**: every price/OHLC input is assumed to be split- and
  dividend-adjusted ("adjusted close" semantics). Levels and stops are
  therefore expressed in adjusted-price space.
- **Completed bars only**: callers must pass series of *completed* bars
  (no in-progress / look-ahead bar). These functions do no bar filtering.
- **Direction-aware**: long/short helpers accept ``direction='long'`` or
  ``direction='short'``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Sequence, Union

import numpy as np
import pandas as pd

ArrayLike = Union[Sequence[float], np.ndarray, pd.Series]

__all__ = [
    "atr",
    "atr_levels",
    "r_multiple",
    "unrealized_r",
    "distance_to_stop_pct",
    "position_size_fixed_fractional",
    "kelly_fraction",
    "fractional_kelly",
    "days_held",
    "position_vol",
    "position_beta",
]


def _to_1d_array(x: ArrayLike) -> np.ndarray:
    """Coerce an array-like (list / ndarray / pandas Series) to a 1-D float array."""
    arr = np.asarray(x, dtype=float).ravel()
    return arr


# --------------------------------------------------------------------------- #
# Volatility / ranges
# --------------------------------------------------------------------------- #
def atr(high: ArrayLike, low: ArrayLike, close: ArrayLike, period: int = 14) -> float:
    """Average True Range using Wilder's smoothing.

    True Range for bar *t* (t >= 1) is::

        TR_t = max(
            high_t - low_t,
            abs(high_t - close_{t-1}),
            abs(low_t  - close_{t-1}),
        )

    The first bar's TR is ``high_0 - low_0`` (no prior close available). ATR is
    Wilder's smoothed average of TR, which is an EMA with ``alpha = 1/period``::

        ATR_period = mean(TR_1 .. TR_period)                 # seed (Wilder)
        ATR_t      = (ATR_{t-1} * (period - 1) + TR_t) / period

    Parameters
    ----------
    high, low, close : array-like
        Adjusted OHLC component series of equal length, oldest-to-newest, on
        completed bars only.
    period : int, default 14
        Wilder smoothing period.

    Returns
    -------
    float
        The most recent ATR value. ``nan`` if there are fewer than
        ``period + 1`` bars (insufficient data to seed the average).
    """
    h = _to_1d_array(high)
    l = _to_1d_array(low)
    c = _to_1d_array(close)

    n = len(c)
    if not (len(h) == len(l) == n):
        raise ValueError("high, low, close must have equal length")
    if period < 1:
        raise ValueError("period must be >= 1")
    if n < period + 1:
        return float("nan")

    # True Range. tr[0] has no prior close, so use high-low.
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev_close = c[:-1]
    hl = h[1:] - l[1:]
    hc = np.abs(h[1:] - prev_close)
    lc = np.abs(l[1:] - prev_close)
    tr[1:] = np.maximum.reduce([hl, hc, lc])

    # Wilder seed: simple average of the first `period` true ranges
    # (using TR over bars 1..period, i.e. the first `period` *real* TRs).
    # We seed from tr[1:period+1] which are the first `period` TRs that use a
    # prior close, then smooth across the remainder.
    seed = np.mean(tr[1 : period + 1])
    atr_val = seed
    for t in range(period + 1, n):
        atr_val = (atr_val * (period - 1) + tr[t]) / period
    return float(atr_val)


def atr_levels(
    entry: float,
    atr: float,
    stop_mult: float = 2.0,
    target_mult: float = 3.0,
    direction: str = "long",
) -> Dict[str, float]:
    """ATR-based protective stop and profit target around an entry.

    For a long::

        stop   = entry - stop_mult   * atr
        target = entry + target_mult * atr

    For a short the offsets are mirrored::

        stop   = entry + stop_mult   * atr
        target = entry - target_mult * atr

    Parameters
    ----------
    entry : float
        Entry (fill) price, adjusted-price space.
    atr : float
        Current ATR (see :func:`atr`).
    stop_mult, target_mult : float
        ATR multiples for the stop and target.
    direction : {'long', 'short'}

    Returns
    -------
    dict
        ``{"stop": float, "target": float}``.
    """
    d = direction.lower()
    if d not in ("long", "short"):
        raise ValueError("direction must be 'long' or 'short'")
    if d == "long":
        stop = entry - stop_mult * atr
        target = entry + target_mult * atr
    else:
        stop = entry + stop_mult * atr
        target = entry - target_mult * atr
    return {"stop": float(stop), "target": float(target)}


# --------------------------------------------------------------------------- #
# R-multiple / risk geometry
# --------------------------------------------------------------------------- #
def r_multiple(current: float, entry: float, stop: float) -> float:
    """Signed, direction-aware R-multiple of the move from entry.

    "1R" is the initial per-share risk, ``|entry - stop|``. The R-multiple is
    the realized/unrealized move expressed in units of that risk, signed so a
    favourable move is positive regardless of long/short::

        risk      = |entry - stop|
        direction = +1 if stop < entry (long) else -1 (short)
        R         = direction * (current - entry) / risk

    A move of exactly +1R (price reached entry + risk for a long, or
    entry - risk for a short) returns ``1.0``; hitting the stop returns
    ``-1.0``.

    Returns ``nan`` if ``entry == stop`` (zero risk, undefined).
    """
    risk = abs(entry - stop)
    if risk == 0:
        return float("nan")
    sign = 1.0 if stop < entry else -1.0  # long if stop below entry
    return float(sign * (current - entry) / risk)


def unrealized_r(current: float, entry: float, stop: float) -> float:
    """Unrealized R-multiple of an open position (alias of :func:`r_multiple`).

    Identical math to :func:`r_multiple`; named separately so call sites read
    clearly when measuring an *open* position's current gain/loss in R.
    """
    return r_multiple(current, entry, stop)


def distance_to_stop_pct(entry: float, stop: float) -> float:
    """Percent distance from entry to stop, relative to entry.

    Returns the fraction (not ``*100``) ``|entry - stop| / |entry|``. E.g. an
    entry of 100 with a stop at 98 returns ``0.02`` (2%).

    Returns ``nan`` if ``entry == 0``.
    """
    if entry == 0:
        return float("nan")
    return float(abs(entry - stop) / abs(entry))


# --------------------------------------------------------------------------- #
# Position sizing
# --------------------------------------------------------------------------- #
def position_size_fixed_fractional(
    account_value: float, risk_pct: float, per_share_risk: float
) -> float:
    """Fixed-fractional position size (shares) for a target dollar risk.

    Risk a fixed fraction of the account on the trade::

        dollar_risk = account_value * risk_pct
        shares      = dollar_risk / per_share_risk

    ``risk_pct`` is a fraction (0.02 == 2%). ``per_share_risk`` is the
    distance from entry to stop in price terms (``|entry - stop|``).

    Returns shares as a float (caller decides whether to floor / round).
    Returns ``0.0`` if ``per_share_risk <= 0`` (no defined risk → no size).
    """
    if per_share_risk <= 0:
        return 0.0
    dollar_risk = account_value * risk_pct
    return float(dollar_risk / per_share_risk)


def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """Kelly-optimal fraction of capital to wager.

    With ``p`` = win probability, ``q = 1 - p`` = loss probability, and
    ``b`` = win/loss payoff ratio (avg win / avg loss)::

        f* = (b * p - q) / b = p - q / b

    A negative result means the edge is unfavourable (don't bet); it is
    returned as-is so callers can detect/clamp it.

    Returns ``nan`` if ``win_loss_ratio <= 0`` (payoff undefined).
    """
    if win_loss_ratio <= 0:
        return float("nan")
    p = win_rate
    q = 1.0 - win_rate
    return float(p - q / win_loss_ratio)


def fractional_kelly(f: float, frac: float = 0.25) -> float:
    """Scale a full-Kelly fraction down to a fractional-Kelly bet.

    Full Kelly is volatile and assumes perfectly known edge; practitioners
    use a fraction (commonly 0.25–0.5×)::

        f_frac = f * frac

    Negative full-Kelly inputs pass through scaled (still negative), so the
    caller can treat "negative → no trade" uniformly.
    """
    return float(f * frac)


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def days_held(
    entry_date: Union[str, date, datetime, pd.Timestamp],
    now: Union[str, date, datetime, pd.Timestamp],
) -> int:
    """Whole calendar days a position has been held.

    Accepts dates / datetimes / ISO strings / pandas Timestamps. Comparison is
    done on the calendar-date component (time-of-day ignored), so a position
    opened and closed the same day returns ``0``.

    Returns a non-negative int (``max(0, delta)``).
    """
    d0 = pd.Timestamp(entry_date).normalize()
    d1 = pd.Timestamp(now).normalize()
    delta = (d1 - d0).days
    return int(max(0, delta))


# --------------------------------------------------------------------------- #
# Position risk vs market (reuses risk.py when available)
# --------------------------------------------------------------------------- #
def position_vol(returns: ArrayLike, periods_per_year: int = 252) -> float:
    """Annualized volatility of a single position's return series.

    Delegates to :func:`analytics.risk.annualized_volatility` when the
    ``risk`` module is present (single source of truth), else computes it
    locally::

        vol = std(returns, ddof=1) * sqrt(periods_per_year)

    ``returns`` are simple period returns (e.g. daily) on completed bars.
    Returns ``nan`` if fewer than 2 observations.
    """
    try:  # reuse the package's risk module if it exists
        from . import risk as _risk  # type: ignore

        if hasattr(_risk, "annualized_volatility"):
            return float(_risk.annualized_volatility(returns, periods_per_year))
    except Exception:
        pass

    r = _to_1d_array(returns)
    if r.size < 2:
        return float("nan")
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))


def position_beta(asset_returns: ArrayLike, market_returns: ArrayLike) -> float:
    """Beta of a position's returns versus the market (benchmark) returns.

    Delegates to :func:`analytics.risk.beta` when the ``risk`` module is
    present, else computes it locally::

        beta = cov(asset, market) / var(market)

    Both series must be aligned (same length, same bars). Returns ``nan`` if
    fewer than 2 observations or the market has zero variance.
    """
    try:  # reuse the package's risk module if it exists
        from . import risk as _risk  # type: ignore

        if hasattr(_risk, "beta"):
            return float(_risk.beta(asset_returns, market_returns))
    except Exception:
        pass

    a = _to_1d_array(asset_returns)
    m = _to_1d_array(market_returns)
    if a.size != m.size:
        raise ValueError("asset_returns and market_returns must be the same length")
    if a.size < 2:
        return float("nan")
    var_m = np.var(m, ddof=1)
    if var_m == 0:
        return float("nan")
    cov_am = np.cov(a, m, ddof=1)[0, 1]
    return float(cov_am / var_m)
