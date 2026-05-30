"""Price/momentum sector rotation — the BACKBONE of the rotation scan.

This module turns daily price series for the 11 SPDR sector ETFs (+ SPY) into
the price-side rotation signals described in the sector-rotation research spec:

- **Relative Strength (RS)** of each sector ETF vs. SPY.
- **RRG** (Relative Rotation Graph): ``RS-Ratio`` + ``RS-Momentum`` and the
  Leading / Weakening / Lagging / Improving quadrant each sector sits in.
- **Multi-timeframe momentum** — Rate of Change over 1w / 1m / 3m windows.
- **Breadth proxy** — share of sectors above their own moving average (a cheap,
  ETF-only stand-in for true constituent breadth, which would need per-name
  holdings data).
- **Money-flow proxies** — On-Balance Volume (OBV), Relative Volume (RVOL) and
  a 20-day relative-volume ratio per sector ETF.

Layering (mirrors ``backend/analytics/`` and ``sector_rotation/sectors.py``)
---------------------------------------------------------------------------
- Everything except :func:`fetch_rotation_ohlcv` and :func:`scan_market_rotation`
  is **PURE**: numpy / pandas / stdlib only, all data passed in, deterministic,
  unit-tested. No network, no disk, no look-ahead.
- :func:`fetch_rotation_ohlcv` is the **only** network-touching function. It
  reuses :func:`hermes.charlotte.data_fetch.fetch_ohlcv` (adjusted close,
  per-process cached) for the 11 sector ETFs + SPY, **drops the most recent
  (possibly in-progress) bar** so there is no look-ahead, is exception-wrapped,
  and degrades to an empty dict — it never raises into the caller.
- :func:`scan_market_rotation` is a thin IO wrapper: fetch, then run the pure
  compute on completed bars. It also degrades gracefully.

No-look-ahead contract
----------------------
``fetch_ohlcv`` returns bars through "now", so during market hours the tail bar
can be partial. The IO layer drops that tail bar (see :func:`_completed_close`)
before any computation, exactly like ``backend/scan_analytics.py``. The pure
functions assume the series they receive already contains only completed bars.

Formulas (verbatim from the research spec, StockCharts / RRG-Lite)
------------------------------------------------------------------
- ``RS              = (Sector Price / SPY Price) * 100``
- ``RS_Ratio        = 100 + (RS - SMA(RS, n)) / StdDev(RS, n)``        (n=14)
- ``RS_Mom_value    = RS_Ratio / RS_Ratio[n ago] - 1``
- ``RS_Momentum     = 100 + RS_Mom_value / StdDev(RS_Mom_value, n)``   (n=14)
- ``ROC(n)          = (P_t / P_{t-n} - 1) * 100``
- ``OBV``: cumulative signed volume by daily close direction.
- ``RVOL            = Volume_t / SMA(Volume, 20)``

Quadrants (RS_Ratio, RS_Momentum thresholded at 100):
    RS_Ratio > 100, RS_Mom > 100 -> Leading    (rotate IN, most bullish)
    RS_Ratio > 100, RS_Mom < 100 -> Weakening   (caution, losing steam)
    RS_Ratio < 100, RS_Mom < 100 -> Lagging     (rotate OUT, most bearish)
    RS_Ratio < 100, RS_Mom > 100 -> Improving    (early rotation IN, watch)

Sources
-------
- StockCharts RRG (RS-Ratio / RS-Momentum) methodology; RRG-Lite reference impl.
- Rate-of-Change & OBV: J. Welles Wilder / standard TA definitions.
- Sector-rotation research spec sections 1.2–1.5.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from sector_rotation.sectors import (
    ALL_ROTATION_SYMBOLS,
    BENCHMARK,
    SECTOR_ETF_SYMBOLS,
    etf_to_sector,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# tunables (research-spec defaults)
# --------------------------------------------------------------------------- #
RS_PERIOD = 14            # RS-Ratio / RS-Momentum z-score & ROC window
ROC_WINDOWS: Dict[str, int] = {"1w": 5, "1m": 21, "3m": 63}  # trading days
RVOL_WINDOW = 20          # relative-volume lookback
BREADTH_MA = 50           # MA window for the ETF-level breadth proxy

# Quadrant labels (canonical, used everywhere downstream).
LEADING = "Leading"
WEAKENING = "Weakening"
LAGGING = "Lagging"
IMPROVING = "Improving"
NEUTRAL = "Neutral"       # only when ratio/momentum are not computable

# How many completed bars we ask the IO layer for: enough for the 63-day ROC
# plus the 14-period RS z-scoring with comfortable head-room.
_FETCH_DAYS = 420


# --------------------------------------------------------------------------- #
# small pure helpers
# --------------------------------------------------------------------------- #
def _as_series(prices: Sequence[float] | pd.Series, name: str = "price") -> pd.Series:
    """Coerce to a float pandas Series, dropping NaNs. PURE."""
    if isinstance(prices, pd.Series):
        s = prices.astype("float64")
    else:
        s = pd.Series(list(prices), dtype="float64", name=name)
    return s.dropna()


def _finite(x: float) -> Optional[float]:
    """Return ``x`` as a plain float if finite, else ``None``. PURE."""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None


# --------------------------------------------------------------------------- #
# 1.2  Relative strength + RRG (RS-Ratio / RS-Momentum / quadrant)
# --------------------------------------------------------------------------- #
def relative_strength(
    sector_prices: Sequence[float] | pd.Series,
    benchmark_prices: Sequence[float] | pd.Series,
) -> pd.Series:
    """RS = (sector / benchmark) * 100, aligned on the common index. PURE.

    Both inputs are coerced to float Series. When the inputs are bare sequences
    they are aligned positionally (a fresh RangeIndex); when they are pandas
    Series they are aligned on their (shared) index, then divided. Non-finite
    or zero-benchmark points drop out.
    """
    s = _as_series(sector_prices)
    b = _as_series(benchmark_prices)
    if not isinstance(sector_prices, pd.Series) and not isinstance(
        benchmark_prices, pd.Series
    ):
        # positional alignment for bare sequences
        s = s.reset_index(drop=True)
        b = b.reset_index(drop=True)
    df = pd.concat([s.rename("s"), b.rename("b")], axis=1).dropna()
    df = df[df["b"] != 0.0]
    rs = (df["s"] / df["b"]) * 100.0
    return rs.replace([np.inf, -np.inf], np.nan).dropna()


def rs_ratio(rs: pd.Series, period: int = RS_PERIOD) -> pd.Series:
    """RS-Ratio = 100 + (RS - SMA(RS,n)) / StdDev(RS,n). PURE.

    Z-score normalization of relative strength, centered at 100. A point is
    NaN until ``period`` observations are available, or when the rolling stddev
    is 0 (flat RS — undefined z-score).
    """
    rs = _as_series(rs)
    if period < 2:
        raise ValueError("period must be >= 2")
    ma = rs.rolling(period).mean()
    sd = rs.rolling(period).std(ddof=0)
    sd = sd.where(sd > 0)  # avoid divide-by-zero -> NaN
    return 100.0 + (rs - ma) / sd


def rs_momentum(ratio: pd.Series, period: int = RS_PERIOD) -> pd.Series:
    """RS-Momentum = 100 + z-score of ROC(RS-Ratio, n). PURE.

    Per the spec: ``mom_value = RS_Ratio / RS_Ratio[n ago] - 1`` then normalize
    by its own rolling stddev (centered at 100). NaN until enough observations,
    or when the normalizing stddev is 0.
    """
    ratio = _as_series(ratio)
    if period < 2:
        raise ValueError("period must be >= 2")
    prev = ratio.shift(period)
    mom_value = (ratio / prev) - 1.0
    mom_value = mom_value.replace([np.inf, -np.inf], np.nan)
    sd = mom_value.rolling(period).std(ddof=0)
    sd = sd.where(sd > 0)
    return 100.0 + mom_value / sd


def rrg_quadrant(ratio: Optional[float], momentum: Optional[float]) -> str:
    """Assign the RRG quadrant from the latest (RS-Ratio, RS-Momentum). PURE.

    Threshold is 100 on both axes. Exactly-100 is treated as the non-leading /
    non-lagging side (``>`` is strict). When either value is missing or
    non-finite the quadrant is :data:`NEUTRAL`.

    >>> rrg_quadrant(104.0, 102.0)
    'Leading'
    >>> rrg_quadrant(104.0, 98.0)
    'Weakening'
    >>> rrg_quadrant(96.0, 98.0)
    'Lagging'
    >>> rrg_quadrant(96.0, 102.0)
    'Improving'
    >>> rrg_quadrant(None, 102.0)
    'Neutral'
    """
    r = _finite(ratio) if ratio is not None else None
    m = _finite(momentum) if momentum is not None else None
    if r is None or m is None:
        return NEUTRAL
    if r > 100.0 and m > 100.0:
        return LEADING
    if r > 100.0 and m <= 100.0:
        return WEAKENING
    if r <= 100.0 and m <= 100.0:
        return LAGGING
    return IMPROVING


def compute_rrg(
    sector_prices: Sequence[float] | pd.Series,
    benchmark_prices: Sequence[float] | pd.Series,
    period: int = RS_PERIOD,
) -> Dict[str, Any]:
    """Full RRG for one sector vs. the benchmark. PURE.

    Returns the latest ``rs_ratio``, ``rs_momentum`` (floats or ``None``) and
    the ``quadrant``. Degrades to NEUTRAL with ``None`` values when the series
    are too short to z-score (needs ~``2*period`` points for a momentum read).
    """
    rs = relative_strength(sector_prices, benchmark_prices)
    ratio = rs_ratio(rs, period)
    mom = rs_momentum(ratio, period)
    last_ratio = _finite(ratio.iloc[-1]) if len(ratio) else None
    last_mom = _finite(mom.iloc[-1]) if len(mom) else None
    return {
        "rs_ratio": last_ratio,
        "rs_momentum": last_mom,
        "quadrant": rrg_quadrant(last_ratio, last_mom),
    }


# --------------------------------------------------------------------------- #
# 1.3  Multi-timeframe Rate of Change
# --------------------------------------------------------------------------- #
def roc(prices: Sequence[float] | pd.Series, periods: int) -> Optional[float]:
    """Rate of Change over ``periods`` bars, in percent. PURE.

    ``ROC(n) = (P_t / P_{t-n} - 1) * 100``. Returns ``None`` when there are not
    enough bars or the reference price is non-positive.
    """
    s = _as_series(prices)
    if periods < 1 or len(s) <= periods:
        return None
    p_now = float(s.iloc[-1])
    p_then = float(s.iloc[-1 - periods])
    if p_then <= 0:
        return None
    return _finite((p_now / p_then - 1.0) * 100.0)


def multi_timeframe_roc(
    prices: Sequence[float] | pd.Series,
    windows: Mapping[str, int] = ROC_WINDOWS,
) -> Dict[str, Optional[float]]:
    """ROC over each named window (default 1w/1m/3m). PURE.

    >>> r = multi_timeframe_roc([100, 101, 102, 103, 104, 110])
    >>> round(r["1w"], 2)
    10.0
    """
    return {label: roc(prices, n) for label, n in windows.items()}


# --------------------------------------------------------------------------- #
# 1.5  Money-flow proxies (OBV, RVOL, relative volume)
# --------------------------------------------------------------------------- #
def on_balance_volume(
    close: Sequence[float] | pd.Series,
    volume: Sequence[float] | pd.Series,
) -> pd.Series:
    """On-Balance Volume series. PURE.

    Cumulative signed volume: +volume on an up-close day, -volume on a down
    day, unchanged on a flat day. Aligned positionally on the shorter length.
    """
    c = _as_series(close).reset_index(drop=True)
    v = _as_series(volume).reset_index(drop=True)
    n = min(len(c), len(v))
    c, v = c.iloc[:n], v.iloc[:n]
    if n == 0:
        return pd.Series([], dtype="float64")
    direction = np.sign(c.diff().fillna(0.0))
    signed = direction * v
    signed.iloc[0] = 0.0  # no prior close to compare the first bar against
    return signed.cumsum().rename("obv")


def relative_volume(
    volume: Sequence[float] | pd.Series, window: int = RVOL_WINDOW
) -> Optional[float]:
    """RVOL = latest volume / SMA(volume, window). PURE.

    Returns ``None`` when there are fewer than ``window`` bars or the average
    volume is non-positive. >1.5 ~ volume spike; <0.8 ~ loss of interest.
    """
    v = _as_series(volume)
    if window < 1 or len(v) < window:
        return None
    avg = float(v.iloc[-window:].mean())
    if avg <= 0:
        return None
    return _finite(float(v.iloc[-1]) / avg)


def money_flow_proxies(
    close: Sequence[float] | pd.Series,
    volume: Sequence[float] | pd.Series,
    window: int = RVOL_WINDOW,
) -> Dict[str, Any]:
    """Per-ETF money-flow block: OBV slope sign, RVOL, and OBV last value. PURE.

    ``obv_rising`` compares the last OBV value to its value ``window`` bars ago
    (a coarse slope sign): ``True`` rising, ``False`` falling, ``None`` flat /
    insufficient data. Combine ``obv_rising`` with price direction downstream
    (rising OBV + rising price = accumulation).
    """
    obv = on_balance_volume(close, volume)
    obv_last = _finite(obv.iloc[-1]) if len(obv) else None
    obv_rising: Optional[bool] = None
    if len(obv) > window:
        delta = float(obv.iloc[-1]) - float(obv.iloc[-1 - window])
        if delta != 0.0:
            obv_rising = delta > 0.0
    return {
        "obv": obv_last,
        "obv_rising": obv_rising,
        "rvol": relative_volume(volume, window),
    }


# --------------------------------------------------------------------------- #
# 1.4  Breadth proxy (ETF-level: share of sectors above their own MA)
# --------------------------------------------------------------------------- #
def _above_own_ma(prices: Sequence[float] | pd.Series, ma_window: int) -> Optional[bool]:
    """``True`` iff the latest close is above its own SMA(ma_window). PURE."""
    s = _as_series(prices)
    if ma_window < 1 or len(s) < ma_window:
        return None
    ma = float(s.iloc[-ma_window:].mean())
    last = float(s.iloc[-1])
    if not math.isfinite(ma):
        return None
    return last > ma


def breadth_proxy(
    sector_closes: Mapping[str, Sequence[float] | pd.Series],
    ma_window: int = BREADTH_MA,
) -> Dict[str, Any]:
    """Share of sector ETFs trading above their own SMA(ma_window). PURE.

    This is a *proxy* for true constituent breadth (which needs per-name holdings
    data we do not fetch here): instead of "% of XLF names above 50-DMA" it is
    "% of the 11 sector ETFs above their own 50-DMA". A cheap, robust read of how
    broad-based the rotation is across sectors.

    Returns ``pct_above`` in [0, 100] (or ``None`` if nothing is computable),
    the ``count_above`` / ``total`` counts, and per-sector booleans.
    """
    per_sector: Dict[str, Optional[bool]] = {}
    for sym, closes in sector_closes.items():
        per_sector[sym] = _above_own_ma(closes, ma_window)
    decided = [v for v in per_sector.values() if v is not None]
    count_above = sum(1 for v in decided if v)
    total = len(decided)
    pct = (count_above / total * 100.0) if total else None
    return {
        "pct_above": _finite(pct) if pct is not None else None,
        "count_above": count_above,
        "total": total,
        "per_sector": per_sector,
        "ma_window": ma_window,
    }


# --------------------------------------------------------------------------- #
# pure top-level assembler: build the full price-rotation block from series
# --------------------------------------------------------------------------- #
def build_rotation_block(
    sector_series: Mapping[str, Mapping[str, Sequence[float] | pd.Series]],
    benchmark_close: Sequence[float] | pd.Series,
    period: int = RS_PERIOD,
    roc_windows: Mapping[str, int] = ROC_WINDOWS,
) -> Dict[str, Any]:
    """Assemble the full price/momentum rotation block from price series. PURE.

    Parameters
    ----------
    sector_series : mapping of ETF symbol -> {"close": [...], "volume": [...]}
        Completed-bar adjusted-close (and raw volume) series per sector ETF.
    benchmark_close : sequence
        Completed-bar adjusted-close series for the benchmark (SPY).

    Returns
    -------
    dict
        ``sectors``: per-ETF dict with sector name, RRG (ratio/momentum/quadrant),
        multi-timeframe ROC, and money-flow proxies.
        ``breadth``: the ETF-level breadth proxy.
        ``benchmark``: the benchmark symbol used.
    All per-sector failures degrade to NEUTRAL / ``None`` fields; never raises
    on a single bad series.
    """
    out_sectors: Dict[str, Any] = {}
    closes_for_breadth: Dict[str, Sequence[float] | pd.Series] = {}

    for sym, series in sector_series.items():
        try:
            close = series.get("close", [])
            volume = series.get("volume", [])
            closes_for_breadth[sym] = close
            rrg = compute_rrg(close, benchmark_close, period)
            block = {
                "sector": etf_to_sector(sym),
                "rs_ratio": rrg["rs_ratio"],
                "rs_momentum": rrg["rs_momentum"],
                "quadrant": rrg["quadrant"],
                "roc": multi_timeframe_roc(close, roc_windows),
                "money_flow": money_flow_proxies(close, volume),
            }
        except Exception as e:  # noqa: BLE001 - one bad series must not sink the scan
            logger.debug("build_rotation_block: %s failed: %s", sym, e)
            block = {
                "sector": etf_to_sector(sym),
                "rs_ratio": None,
                "rs_momentum": None,
                "quadrant": NEUTRAL,
                "roc": {k: None for k in roc_windows},
                "money_flow": {"obv": None, "obv_rising": None, "rvol": None},
            }
        out_sectors[sym] = block

    try:
        breadth = breadth_proxy(closes_for_breadth)
    except Exception as e:  # noqa: BLE001
        logger.debug("build_rotation_block: breadth failed: %s", e)
        breadth = {
            "pct_above": None,
            "count_above": 0,
            "total": 0,
            "per_sector": {},
            "ma_window": BREADTH_MA,
        }

    return {"sectors": out_sectors, "breadth": breadth, "benchmark": BENCHMARK}


# =========================================================================== #
# IO LAYER — the ONLY network-touching code in this module.
# Exception-wrapped, completed-bars-only, degrades to {} / never raises.
# =========================================================================== #
def _completed_close(df: Optional[pd.DataFrame], column: str) -> Optional[pd.Series]:
    """Adjusted/raw column from a fetch_ohlcv frame, dropping the in-progress bar.

    IO-adjacent helper. ``fetch_ohlcv`` returns bars through "now" (auto_adjust
    =False, so both ``Adj Close`` and raw ``Close``/``Volume`` are present), and
    the tail bar can be partial during market hours — drop it to avoid
    look-ahead. Returns ``None`` if the frame/column is missing or too short.
    """
    if df is None or getattr(df, "empty", True):
        return None
    if column not in df.columns:
        # Adj Close may be absent if a provider already adjusted; fall back.
        if column == "Adj Close" and "Close" in df.columns:
            column = "Close"
        else:
            return None
    completed = df.iloc[:-1]  # drop the (possibly in-progress) most recent bar
    if len(completed) < 2:
        return None
    return completed[column].astype("float64").dropna()


def fetch_rotation_ohlcv(
    symbols: Sequence[str] = ALL_ROTATION_SYMBOLS,
    days: int = _FETCH_DAYS,
) -> Dict[str, Dict[str, pd.Series]]:
    """IO: fetch completed-bar adjusted close + volume for the rotation universe.

    Reuses :func:`hermes.charlotte.data_fetch.fetch_ohlcv` (per-process cached,
    adjusted close available because it downloads with ``auto_adjust=False``).
    For each symbol returns ``{"close": <Adj Close Series>, "volume": <Volume
    Series>}`` on **completed bars only** (the in-progress tail bar is dropped).

    Fully exception-wrapped and degrades gracefully: a symbol that fails to
    fetch is simply absent from the result. Returns ``{}`` (never raises) if the
    fetcher import itself fails.
    """
    try:
        import sys

        if "/home/user/.hermes" not in sys.path:
            sys.path.insert(0, "/home/user/.hermes")
        from hermes.charlotte.data_fetch import fetch_ohlcv  # type: ignore
    except Exception as e:  # pragma: no cover - dep/path issue degrades to empty
        logger.warning("fetch_rotation_ohlcv: data_fetch unavailable: %s", e)
        return {}

    out: Dict[str, Dict[str, pd.Series]] = {}
    for sym in symbols:
        try:
            df = fetch_ohlcv(sym, days=days)
        except Exception as e:  # noqa: BLE001 - one bad symbol must not abort
            logger.debug("fetch_rotation_ohlcv: %s fetch failed: %s", sym, e)
            continue
        close = _completed_close(df, "Adj Close")
        volume = _completed_close(df, "Volume")
        if close is None:
            logger.debug("fetch_rotation_ohlcv: %s no usable close series", sym)
            continue
        out[sym] = {
            "close": close,
            "volume": volume if volume is not None else pd.Series([], dtype="float64"),
        }
    return out


def scan_market_rotation(
    sector_symbols: Sequence[str] = SECTOR_ETF_SYMBOLS,
    benchmark: str = BENCHMARK,
    days: int = _FETCH_DAYS,
) -> Dict[str, Any]:
    """IO wrapper: fetch the universe, then run the PURE rotation compute.

    Pulls completed-bar series for the sector ETFs + benchmark, then delegates
    to :func:`build_rotation_block`. Degrades gracefully: if the benchmark or
    all sectors are unavailable, returns a block with empty ``sectors`` and
    ``None`` breadth rather than raising.
    """
    try:
        symbols = tuple(dict.fromkeys((*sector_symbols, benchmark)))
        fetched = fetch_rotation_ohlcv(symbols, days=days)
        bench = fetched.get(benchmark, {}).get("close")
        if bench is None or len(bench) == 0:
            logger.warning("scan_market_rotation: benchmark %s unavailable", benchmark)
            return {
                "sectors": {},
                "breadth": {
                    "pct_above": None,
                    "count_above": 0,
                    "total": 0,
                    "per_sector": {},
                    "ma_window": BREADTH_MA,
                },
                "benchmark": benchmark,
            }
        sector_series = {
            sym: fetched[sym] for sym in sector_symbols if sym in fetched
        }
        return build_rotation_block(sector_series, bench)
    except Exception as e:  # noqa: BLE001 - IO wrapper never raises into caller
        logger.warning("scan_market_rotation failed: %s", e)
        return {
            "sectors": {},
            "breadth": {
                "pct_above": None,
                "count_above": 0,
                "total": 0,
                "per_sector": {},
                "ma_window": BREADTH_MA,
            },
            "benchmark": benchmark,
        }
