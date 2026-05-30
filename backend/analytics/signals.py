"""Pure technical-signal functions — deterministic, network-free.

Every function here takes data IN (numpy arrays / pandas Series / scalars) and
returns numbers or dicts. There is NO network or disk I/O: the caller (the
wiring / fetch layer) is responsible for pulling and cleaning data.

Conventions
-----------
- **Adjusted close**: price/OHLC inputs are assumed split- and
  dividend-adjusted ("adjusted close" semantics). Levels are in adjusted space.
- **Completed bars only**: callers must pass series of *completed* bars (the
  in-progress / today's incomplete bar dropped upstream). These functions do
  no bar filtering and never peek forward — every value at index ``t`` is
  computed from data at indices ``<= t``.
- **Returns / ROC** are simple (arithmetic) percentage changes, expressed as
  fractions unless a function name says ``_pct`` and documents a 0–100 scale.

Dependency-light: numpy + pandas + stdlib only (no scipy/TA-Lib).

References
----------
- Wilder, J. Welles. *New Concepts in Technical Trading Systems* (1978) — RSI,
  ATR, Wilder smoothing.
- Appel, Gerald. *Technical Analysis: Power Tools for Active Investors* — MACD.
- Murphy, John J. *Technical Analysis of the Financial Markets* — divergence,
  support/resistance, moving-average structure.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

ArrayLike = Union[Sequence[float], np.ndarray, pd.Series]

__all__ = [
    "roc",
    "relative_strength",
    "rsi",
    "macd",
    "detect_divergence",
    "ma_structure",
    "support_resistance",
    "rvol",
    "gap_pct",
    "pct_of_52w_range",
    "days_to_earnings",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _to_1d_array(x: ArrayLike) -> np.ndarray:
    """Coerce an array-like (list / ndarray / pandas Series) to a 1-D float array.

    NaNs are *preserved* (callers needing NaN-free data should clean upstream);
    most functions here index from the tail, so leading NaNs are harmless.
    """
    return np.asarray(x, dtype=float).ravel()


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average over a 1-D array (pandas ``ewm`` convention).

    Uses ``alpha = 2 / (span + 1)`` and ``adjust=False`` (recursive form), which
    is the standard EMA used for MACD::

        ema_0 = values_0
        ema_t = alpha * values_t + (1 - alpha) * ema_{t-1}

    Returns an array the same length as ``values``.
    """
    if span < 1:
        raise ValueError("span must be >= 1")
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    if values.size == 0:
        return out
    out[0] = values[0]
    for t in range(1, values.size):
        out[t] = alpha * values[t] + (1.0 - alpha) * out[t - 1]
    return out


def _local_max_idx(values: np.ndarray, order: int) -> np.ndarray:
    """Indices of strict local maxima (a value greater than its ``order`` neighbours).

    ``argrelextrema``-style without scipy: index ``i`` is a local max if
    ``values[i] > values[i-k]`` and ``values[i] > values[i+k]`` for all
    ``1 <= k <= order``. No look-ahead concern for *signal generation* because
    the caller only inspects extrema within the already-completed lookback
    window; the strict comparison just locates swing pivots inside that window.
    """
    n = values.size
    idx: List[int] = []
    for i in range(order, n - order):
        window = values[i - order : i + order + 1]
        if values[i] == np.max(window) and np.argmax(window) == order:
            # strict: ensure it is uniquely the max at the centre
            if np.sum(window == values[i]) == 1:
                idx.append(i)
    return np.asarray(idx, dtype=int)


def _local_min_idx(values: np.ndarray, order: int) -> np.ndarray:
    """Indices of strict local minima (mirror of :func:`_local_max_idx`)."""
    n = values.size
    idx: List[int] = []
    for i in range(order, n - order):
        window = values[i - order : i + order + 1]
        if values[i] == np.min(window) and np.argmin(window) == order:
            if np.sum(window == values[i]) == 1:
                idx.append(i)
    return np.asarray(idx, dtype=int)


# --------------------------------------------------------------------------- #
# Momentum
# --------------------------------------------------------------------------- #
def roc(close: ArrayLike, n: int) -> float:
    """Percentage rate-of-change over ``n`` bars.

    Formula
    -------
        ROC = (close_t / close_{t-n} - 1) * 100

    Parameters
    ----------
    close : array-like
        Adjusted close series, oldest-to-newest, completed bars only.
    n : int
        Lookback in bars (>= 1).

    Returns
    -------
    float
        Percent change (e.g. ``5.0`` == +5%). ``nan`` if fewer than ``n + 1``
        bars or the reference price is 0.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    c = _to_1d_array(close)
    if c.size < n + 1:
        return float("nan")
    ref = c[-(n + 1)]
    if ref == 0 or np.isnan(ref) or np.isnan(c[-1]):
        return float("nan")
    return float((c[-1] / ref - 1.0) * 100.0)


def relative_strength(asset_close: ArrayLike, spy_close: ArrayLike, n: int) -> float:
    """Relative strength of an asset versus SPY over ``n`` bars.

    Defined as the difference of the two ``n``-bar percentage changes (asset
    ROC minus benchmark ROC), in percentage points::

        RS = ROC_n(asset) - ROC_n(SPY)

    A positive RS means the asset out-performed SPY over the window. The two
    series need not be the same length (each is measured from its own tail), but
    callers should pass date-aligned, equal-length tails for a clean read.

    Parameters
    ----------
    asset_close, spy_close : array-like
        Adjusted close series, completed bars only.
    n : int
        Lookback in bars.

    Returns
    -------
    float
        Out-/under-performance in percentage points. ``nan`` if either ROC is
        undefined.
    """
    a = roc(asset_close, n)
    s = roc(spy_close, n)
    if np.isnan(a) or np.isnan(s):
        return float("nan")
    return float(a - s)


# --------------------------------------------------------------------------- #
# RSI (Wilder)
# --------------------------------------------------------------------------- #
def rsi(close: ArrayLike, period: int = 14) -> float:
    """Relative Strength Index using Wilder's smoothing.

    Formula
    -------
        delta_t   = close_t - close_{t-1}
        gain_t    = max(delta_t, 0);  loss_t = max(-delta_t, 0)
        avg_gain  = Wilder-smoothed mean of gains  (seed = SMA of first `period`)
        avg_loss  = Wilder-smoothed mean of losses
        RS        = avg_gain / avg_loss
        RSI       = 100 - 100 / (1 + RS)

    Wilder smoothing is an EMA with ``alpha = 1/period``::

        avg_t = (avg_{t-1} * (period - 1) + value_t) / period

    Parameters
    ----------
    close : array-like
        Adjusted close series, oldest-to-newest, completed bars only.
    period : int, default 14

    Returns
    -------
    float
        Latest RSI in [0, 100]. ``nan`` if fewer than ``period + 1`` bars.
        Returns 100.0 when there are no losses over the window (pure uptrend).

    Notes
    -----
    A steadily rising series has ``avg_loss == 0`` → RS = inf → RSI = 100.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    c = _to_1d_array(close)
    if c.size < period + 1:
        return float("nan")

    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed with the simple average of the first `period` gains/losses.
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # Wilder-smooth across the remaining deltas.
    for t in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[t]) / period
        avg_loss = (avg_loss * (period - 1) + losses[t]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0  # flat series → neutral 50
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _rsi_series(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Full RSI series (one value per bar) using Wilder smoothing.

    Leading bars without enough history are ``nan``. Used internally by
    :func:`detect_divergence` so price and RSI extrema can be aligned.
    """
    c = close
    n = c.size
    out = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return out
    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    def _rsi_from(g: float, l: float) -> float:
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[period] = _rsi_from(avg_gain, avg_loss)
    for t in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[t]) / period
        avg_loss = (avg_loss * (period - 1) + losses[t]) / period
        out[t + 1] = _rsi_from(avg_gain, avg_loss)
    return out


# --------------------------------------------------------------------------- #
# MACD
# --------------------------------------------------------------------------- #
def macd(
    close: ArrayLike, fast: int = 12, slow: int = 26, signal: int = 9
) -> Dict[str, float]:
    """Moving Average Convergence Divergence (latest values).

    Formula
    -------
        macd_line   = EMA_fast(close) - EMA_slow(close)
        signal_line = EMA_signal(macd_line)
        histogram   = macd_line - signal_line

    EMAs use the standard ``alpha = 2/(span+1)`` recursive form (pandas
    ``adjust=False``).

    Parameters
    ----------
    close : array-like
        Adjusted close series, completed bars only.
    fast, slow, signal : int
        EMA spans. ``fast < slow`` by convention (12/26/9 default).

    Returns
    -------
    dict
        ``{"macd": float, "signal": float, "hist": float}`` for the latest bar.
        All ``nan`` if fewer than ``slow`` bars.

    Notes
    -----
    On a sustained uptrend the fast EMA leads the slow EMA, so ``macd > 0``;
    on a downtrend ``macd < 0``.
    """
    if not (fast >= 1 and slow >= 1 and signal >= 1):
        raise ValueError("fast, slow, signal must be >= 1")
    c = _to_1d_array(close)
    if c.size < slow:
        return {"macd": float("nan"), "signal": float("nan"), "hist": float("nan")}

    ema_fast = _ema(c, fast)
    ema_slow = _ema(c, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return {
        "macd": float(macd_line[-1]),
        "signal": float(signal_line[-1]),
        "hist": float(hist[-1]),
    }


def _macd_hist_series(close: np.ndarray, fast: int, slow: int, signal: int) -> np.ndarray:
    """Full MACD-histogram series (one value per bar) for divergence detection."""
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line - signal_line


# --------------------------------------------------------------------------- #
# Divergence
# --------------------------------------------------------------------------- #
def detect_divergence(
    price: ArrayLike,
    indicator: ArrayLike,
    lookback: int = 60,
    order: int = 3,
) -> Dict[str, Optional[str]]:
    """Detect bullish / bearish regular divergence between price and an indicator.

    Regular divergence (Murphy): price and a momentum indicator (RSI or
    MACD-histogram) disagree at consecutive swing extrema.

    - **Bearish**: price makes a *higher high* while the indicator makes a
      *lower high* (uptrend losing momentum).
    - **Bullish**: price makes a *lower low* while the indicator makes a
      *higher low* (downtrend losing momentum).

    Logic
    -----
    1. Restrict to the last ``lookback`` completed bars.
    2. Find the two most recent strict local highs (for bearish) / lows (for
       bullish) in *price* using an ``order``-neighbour local-extrema test.
    3. Compare the indicator value at those *same* bar indices.
    No look-ahead: only data inside the closed lookback window is used, and
    extrema require ``order`` bars on each side (so the most recent ``order``
    bars cannot themselves be pivots).

    Parameters
    ----------
    price : array-like
        Adjusted close (or high/low) series, completed bars only.
    indicator : array-like
        A momentum oscillator aligned 1:1 with ``price`` (e.g. RSI series or
        MACD-hist series). Same length as ``price``.
    lookback : int, default 60
        Number of trailing bars to scan.
    order : int, default 3
        Neighbours each side required to qualify as a swing pivot.

    Returns
    -------
    dict
        ``{"bullish": "bullish"|None, "bearish": "bearish"|None}``. A simple
        single-label convenience key ``"signal"`` holds the dominant result
        (bearish wins ties — momentum loss at a high is the more actionable
        warning for a long book) or ``None``.
    """
    p = _to_1d_array(price)
    ind = _to_1d_array(indicator)
    if p.size != ind.size:
        raise ValueError("price and indicator must be the same length")

    out: Dict[str, Optional[str]] = {"bullish": None, "bearish": None, "signal": None}
    if p.size < 2 * order + 2:
        return out

    p_win = p[-lookback:]
    ind_win = ind[-lookback:]
    # If indicator has NaNs in the window (warm-up), bail gracefully.
    if np.isnan(ind_win).all():
        return out

    # --- Bearish: two most recent price highs ---
    high_idx = _local_max_idx(p_win, order)
    if high_idx.size >= 2:
        i_prev, i_curr = high_idx[-2], high_idx[-1]
        price_hh = p_win[i_curr] > p_win[i_prev]
        ind_lh = (
            not np.isnan(ind_win[i_curr])
            and not np.isnan(ind_win[i_prev])
            and ind_win[i_curr] < ind_win[i_prev]
        )
        if price_hh and ind_lh:
            out["bearish"] = "bearish"

    # --- Bullish: two most recent price lows ---
    low_idx = _local_min_idx(p_win, order)
    if low_idx.size >= 2:
        i_prev, i_curr = low_idx[-2], low_idx[-1]
        price_ll = p_win[i_curr] < p_win[i_prev]
        ind_hl = (
            not np.isnan(ind_win[i_curr])
            and not np.isnan(ind_win[i_prev])
            and ind_win[i_curr] > ind_win[i_prev]
        )
        if price_ll and ind_hl:
            out["bullish"] = "bullish"

    out["signal"] = out["bearish"] or out["bullish"]
    return out


# --------------------------------------------------------------------------- #
# Moving-average structure
# --------------------------------------------------------------------------- #
def ma_structure(close: ArrayLike) -> Dict[str, Optional[bool]]:
    """Trend structure from the 50- and 200-bar simple moving averages.

    Computes::

        ma50  = mean(close[-50:])
        ma200 = mean(close[-200:])

    and reports:

    - ``above_50``       : last close > ma50
    - ``above_200``      : last close > ma200
    - ``golden_cross``   : ma50 > ma200 AND it crossed up within the last bar
                           (ma50_{t-1} <= ma200_{t-1} and ma50_t > ma200_t)
    - ``death_cross``    : ma50 < ma200 AND it crossed down within the last bar
    - ``stacked_bullish``: close > ma50 > ma200 (classic bullish stack)

    No look-ahead: the cross test compares the current and immediately prior
    bar's MA pair, both fully in-sample.

    Parameters
    ----------
    close : array-like
        Adjusted close, oldest-to-newest, completed bars only.

    Returns
    -------
    dict
        Booleans for each key above. Keys that cannot be computed (insufficient
        history) are ``None``. ``golden_cross``/``death_cross`` need >= 201 bars
        to test the prior bar; with exactly 200 they report ``False``.
    """
    c = _to_1d_array(close)
    out: Dict[str, Optional[bool]] = {
        "above_50": None,
        "above_200": None,
        "golden_cross": None,
        "death_cross": None,
        "stacked_bullish": None,
    }
    n = c.size
    last = c[-1] if n else float("nan")

    ma50 = float(np.mean(c[-50:])) if n >= 50 else None
    ma200 = float(np.mean(c[-200:])) if n >= 200 else None

    if ma50 is not None:
        out["above_50"] = bool(last > ma50)
    if ma200 is not None:
        out["above_200"] = bool(last > ma200)
    if ma50 is not None and ma200 is not None:
        out["stacked_bullish"] = bool(last > ma50 > ma200)
        # Cross detection needs the prior bar's MA pair.
        if n >= 201:
            ma50_prev = float(np.mean(c[-51:-1]))
            ma200_prev = float(np.mean(c[-201:-1]))
            out["golden_cross"] = bool(ma50_prev <= ma200_prev and ma50 > ma200)
            out["death_cross"] = bool(ma50_prev >= ma200_prev and ma50 < ma200)
        else:
            out["golden_cross"] = False
            out["death_cross"] = False
    return out


# --------------------------------------------------------------------------- #
# Support / resistance
# --------------------------------------------------------------------------- #
def support_resistance(
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    n_pivots: int = 3,
    order: int = 3,
) -> Dict[str, object]:
    """Nearest support and resistance from recent swing pivots.

    Swing pivots are strict local extrema (``order`` neighbours each side):

    - **Resistance** candidates: swing *highs* of ``high`` that lie ABOVE the
      latest close.
    - **Support** candidates: swing *lows* of ``low`` that lie BELOW the latest
      close.

    The nearest level on each side (closest to the last close) is returned, plus
    up to ``n_pivots`` recent levels on each side for context.

    No look-ahead: pivots require ``order`` confirming bars on each side, so the
    most recent ``order`` bars are never treated as confirmed pivots.

    Parameters
    ----------
    high, low, close : array-like
        Equal-length adjusted OHLC component series, completed bars only.
    n_pivots : int, default 3
        Max number of levels to list per side.
    order : int, default 3
        Neighbours each side required to qualify as a pivot.

    Returns
    -------
    dict
        ``{"support": float|None, "resistance": float|None,
           "supports": [..], "resistances": [..]}``. ``None`` when no qualifying
        level exists on that side.
    """
    h = _to_1d_array(high)
    l = _to_1d_array(low)
    c = _to_1d_array(close)
    if not (h.size == l.size == c.size):
        raise ValueError("high, low, close must have equal length")

    out: Dict[str, object] = {
        "support": None,
        "resistance": None,
        "supports": [],
        "resistances": [],
    }
    if c.size < 2 * order + 1:
        return out

    last = c[-1]
    high_pivots = h[_local_max_idx(h, order)]
    low_pivots = l[_local_min_idx(l, order)]

    resistances = sorted({float(x) for x in high_pivots if x > last})
    supports = sorted({float(x) for x in low_pivots if x < last}, reverse=True)

    if resistances:
        out["resistance"] = resistances[0]  # lowest level above price = nearest
        out["resistances"] = resistances[:n_pivots]
    if supports:
        out["support"] = supports[0]  # highest level below price = nearest
        out["supports"] = supports[:n_pivots]
    return out


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #
def rvol(volume: ArrayLike, window: int = 20) -> float:
    """Relative volume: latest bar volume divided by its trailing average.

    Formula
    -------
        RVOL = volume_t / mean(volume[-(window+1):-1])

    The average is taken over the ``window`` bars *prior* to the current bar so
    the current bar is not included in its own baseline (no self-reference).

    Parameters
    ----------
    volume : array-like
        Share/contract volume, oldest-to-newest, completed bars only.
    window : int, default 20

    Returns
    -------
    float
        Ratio (1.0 == average, 2.0 == twice normal). ``nan`` if fewer than
        ``window + 1`` bars or the baseline average is 0.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    v = _to_1d_array(volume)
    if v.size < window + 1:
        return float("nan")
    baseline = float(np.mean(v[-(window + 1) : -1]))
    if baseline == 0 or np.isnan(baseline):
        return float("nan")
    return float(v[-1] / baseline)


# --------------------------------------------------------------------------- #
# Gaps
# --------------------------------------------------------------------------- #
def gap_pct(open_: float, prev_close: float) -> float:
    """Opening gap as a percent of the prior close.

    Formula
    -------
        gap% = (open - prev_close) / prev_close * 100

    Positive = gap up, negative = gap down.

    Parameters
    ----------
    open_ : float
        Today's opening price.
    prev_close : float
        Prior bar's (completed) close.

    Returns
    -------
    float
        Gap in percent. ``nan`` if ``prev_close`` is 0 or NaN.
    """
    if prev_close == 0 or np.isnan(prev_close) or np.isnan(open_):
        return float("nan")
    return float((open_ - prev_close) / prev_close * 100.0)


# --------------------------------------------------------------------------- #
# 52-week range position
# --------------------------------------------------------------------------- #
def pct_of_52w_range(close: float, high_52w: float, low_52w: float) -> float:
    """Where the price sits within its 52-week range, as 0–100.

    Formula
    -------
        pct = (close - low_52w) / (high_52w - low_52w) * 100

    0 == at the 52-week low, 100 == at the 52-week high. The result is clamped
    to [0, 100] so a fresh extreme (close slightly beyond the recorded range)
    doesn't produce a value outside the band.

    Parameters
    ----------
    close : float
        Latest (completed) close.
    high_52w, low_52w : float
        Trailing 52-week high and low (adjusted).

    Returns
    -------
    float
        Position in the range, 0–100. ``nan`` if the range is degenerate
        (``high_52w == low_52w``) or inputs are NaN.
    """
    if np.isnan(close) or np.isnan(high_52w) or np.isnan(low_52w):
        return float("nan")
    rng = high_52w - low_52w
    if rng == 0:
        return float("nan")
    pct = (close - low_52w) / rng * 100.0
    return float(min(100.0, max(0.0, pct)))


# --------------------------------------------------------------------------- #
# Earnings proximity
# --------------------------------------------------------------------------- #
def days_to_earnings(
    earnings_date: Optional[Union[str, date, datetime, pd.Timestamp]],
    now: Union[str, date, datetime, pd.Timestamp],
) -> Optional[int]:
    """Whole calendar days until the next earnings date.

    Pure: the earnings *date* is fetched by the wiring layer (Finnhub calendar)
    and passed in. Comparison is on the calendar-date component (time-of-day
    ignored).

    Parameters
    ----------
    earnings_date : date-like or None
        Next scheduled earnings date. ``None`` → returns ``None`` (unknown).
    now : date-like
        Reference "today".

    Returns
    -------
    int or None
        Days until earnings (negative if the date is in the past; 0 == today).
        ``None`` if ``earnings_date`` is ``None``.
    """
    if earnings_date is None:
        return None
    d_earn = pd.Timestamp(earnings_date).normalize()
    d_now = pd.Timestamp(now).normalize()
    return int((d_earn - d_now).days)
