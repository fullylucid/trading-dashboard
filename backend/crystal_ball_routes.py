"""
Crystal Ball routes — the dark art of prediction, served over HTTP.

Endpoints (all under ``/api/crystal-ball``):

  GET  /{symbol}            -> fused reversal read (probability/direction/confidence)
  GET  /{symbol}/backtest   -> walk-forward backtest of the reversal strategy
  POST /{symbol}/journal    -> log the current read as a tracked prediction
  GET  /journal             -> list tracked predictions (open + resolved)
  POST /journal/resolve     -> resolve aged predictions vs realized forward returns
  GET  /calibration         -> the honest report card (hit-rate, Brier, by-confidence)

NOTE on routing order: the literal paths (``/journal``, ``/calibration``) are
declared BEFORE the ``/{symbol}`` catch-all so FastAPI doesn't read "journal" as a
ticker. All heavy compute runs off the event loop; reads are briefly cached.

Reuses the same no-look-ahead candle feed as the charts
(``scan_analytics._fetch_ohlcv`` -> ``_completed`` -> ``_adj_close``).
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Path as PathParam, Query, Request

logger = logging.getLogger(__name__)

import scan_analytics as _scan_analytics
from cache_manager import CacheManager
from crystal_ball import crystal_ball_read
from crystal_ball.backtest import run_backtest
from crystal_ball import journal as _journal

router = APIRouter(prefix="/api/crystal-ball", tags=["crystal-ball"])

_cache = CacheManager()
_CB_CACHE_TTL = 90
_BT_CACHE_TTL = 300

_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,14}$")
_RANGE_DAYS = {"3m": 93, "6m": 186, "1y": 372, "2y": 740, "5y": 1830}
_CONF_LEVELS = {"low", "medium", "high"}


def _validate_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(s):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    return s


# ---------------------------------------------------------------------------
# shared compute helpers (sync; run via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _arrays_for(sym: str, days: int):
    """Return (close[], volume[]|None, dates[], last_price) on completed bars, or None."""
    raw = _scan_analytics._fetch_ohlcv(sym, days)
    if raw is None or len(raw) == 0:
        return None
    cdf = _scan_analytics._completed(raw)
    if cdf is None or len(cdf) == 0:
        return None
    adj = _scan_analytics._adj_close(cdf)
    if adj is None or len(adj) < 60:
        return {"_thin": True}
    close = pd.to_numeric(adj, errors="coerce").to_numpy(dtype=float)
    volume = None
    if "Volume" in cdf.columns:
        try:
            volume = pd.to_numeric(cdf["Volume"], errors="coerce").to_numpy(dtype=float)
        except Exception:  # noqa: BLE001
            volume = None
    dates = [str(ix)[:10] for ix in cdf.index]
    last_price = None
    try:
        last_price = float(pd.to_numeric(raw["Close"], errors="coerce").dropna().iloc[-1])
    except Exception:  # noqa: BLE001
        last_price = float(close[-1]) if close.size else None
    return {"close": close, "volume": volume, "dates": dates, "last_price": last_price}


def _compute_read(sym: str, days: int, range_label: str) -> Optional[Dict[str, Any]]:
    arr = _arrays_for(sym, days)
    if arr is None:
        return None
    if arr.get("_thin"):
        return {"_thin": True}
    read = crystal_ball_read(sym, arr["close"], volume=arr["volume"], last_price=arr["last_price"])
    read["range"] = range_label
    read["last_close"] = round(float(arr["close"][-1]), 4)
    return read


def _forward_return(sym: str, as_of_iso: str, horizon: int) -> Optional[float]:
    """Signed close-to-close return over ``horizon`` completed bars from ``as_of``.

    Returns None if the horizon hasn't fully elapsed or data is missing — which
    correctly leaves the prediction unresolved until enough time has passed.
    """
    days = max(horizon * 4 + 60, 150)
    cdf = _scan_analytics._completed(_scan_analytics._fetch_ohlcv(sym, days))
    if cdf is None or len(cdf) == 0:
        return None
    adj = _scan_analytics._adj_close(cdf)
    if adj is None or len(adj) < horizon + 2:
        return None
    try:
        ts = pd.Timestamp(as_of_iso)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        target = ts.normalize()
    except Exception:  # noqa: BLE001
        return None
    idx = pd.DatetimeIndex([pd.Timestamp(i).normalize() for i in adj.index])
    pos = int(np.searchsorted(idx.values, np.datetime64(target)))
    if pos >= len(adj):
        return None
    if pos + horizon >= len(adj):
        return None  # horizon not yet elapsed
    base = float(adj.iloc[pos])
    fwd = float(adj.iloc[pos + horizon])
    if base <= 0:
        return None
    return fwd / base - 1.0


# ---------------------------------------------------------------------------
# LITERAL routes (declared before /{symbol} so they aren't read as tickers)
# ---------------------------------------------------------------------------

@router.get("/journal")
async def get_journal(
    symbol: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    open_only: bool = Query(False),
) -> Dict[str, Any]:
    """List tracked predictions, newest first."""
    sym = symbol.strip().upper() if symbol else None
    items = await asyncio.to_thread(
        _journal.list_predictions, sym, limit, not open_only
    )
    return {"count": len(items), "predictions": items}


@router.post("/journal/resolve")
async def resolve_journal(min_age_days: float = Query(1.0, ge=0.0)) -> Dict[str, Any]:
    """Resolve all aged-out predictions against realized forward returns."""
    result = await asyncio.to_thread(_journal.resolve_predictions, _forward_return, min_age_days=min_age_days)
    return result


@router.get("/calibration")
async def get_calibration() -> Dict[str, Any]:
    """The honest report card: hit-rate, Brier, sliced by confidence + probability."""
    return await asyncio.to_thread(_journal.calibration_report)


# ---------------------------------------------------------------------------
# /{symbol} family
# ---------------------------------------------------------------------------

@router.get("/{symbol}")
async def get_crystal_ball(
    request: Request,
    symbol: str = PathParam(..., description="Ticker symbol"),
    range: str = Query("1y", description="3m|6m|1y|2y of history to analyse"),
) -> Dict[str, Any]:
    """Fused reversal read for ``symbol``."""
    sym = _validate_symbol(symbol)
    days = _RANGE_DAYS.get(range.lower(), _RANGE_DAYS["1y"])

    cache_key = f"crystalball:{sym}:{days}"
    cached = await _cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    try:
        result = await asyncio.to_thread(_compute_read, sym, days, range.lower())
    except Exception as e:  # noqa: BLE001
        logger.warning("crystal-ball[%s]: compute failed: %s", sym, e)
        raise HTTPException(status_code=502, detail="Crystal Ball data unavailable") from None

    if result is None:
        raise HTTPException(status_code=404, detail="No data for symbol")
    if result.get("_thin"):
        raise HTTPException(status_code=422, detail="Not enough price history for a read")

    try:
        await _cache.set(cache_key, json.dumps(result), ttl=_CB_CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass
    return result


@router.get("/{symbol}/backtest")
async def backtest_symbol(
    symbol: str = PathParam(..., description="Ticker symbol"),
    range: str = Query("2y", description="history window: 1y|2y|5y"),
    horizon: int = Query(10, ge=1, le=60, description="holding horizon in bars"),
    prob_threshold: float = Query(0.55, ge=0.0, le=1.0),
    min_confidence: str = Query("medium"),
    cost_bps: float = Query(5.0, ge=0.0, le=200.0),
    slippage_bps: float = Query(5.0, ge=0.0, le=200.0),
    allow_short: bool = Query(True),
    allow_long: bool = Query(True),
) -> Dict[str, Any]:
    """Walk-forward backtest of the Crystal Ball reversal strategy on ``symbol``.

    STRICT no-look-ahead (see crystal_ball.backtest). Returns institutional stats,
    a buy&hold benchmark, the trade list, an equity curve, and a calibration read.
    """
    sym = _validate_symbol(symbol)
    if min_confidence not in _CONF_LEVELS:
        raise HTTPException(status_code=400, detail="min_confidence must be low|medium|high")
    days = _RANGE_DAYS.get(range.lower(), _RANGE_DAYS["2y"])

    cache_key = f"cbbacktest:{sym}:{days}:{horizon}:{prob_threshold}:{min_confidence}:{cost_bps}:{slippage_bps}:{allow_short}:{allow_long}"
    cached = await _cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    def _run() -> Optional[Dict[str, Any]]:
        arr = _arrays_for(sym, days)
        if arr is None or arr.get("_thin"):
            return arr
        return run_backtest(
            arr["close"], volume=arr["volume"], dates=arr["dates"],
            horizon=horizon, prob_threshold=prob_threshold, min_confidence=min_confidence,
            cost_bps=cost_bps, slippage_bps=slippage_bps,
            allow_long=allow_long, allow_short=allow_short,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception as e:  # noqa: BLE001
        logger.warning("crystal-ball backtest[%s]: failed: %s", sym, e)
        raise HTTPException(status_code=502, detail="Backtest failed") from None

    if result is None:
        raise HTTPException(status_code=404, detail="No data for symbol")
    if result.get("_thin"):
        raise HTTPException(status_code=422, detail="Not enough price history to backtest")
    result["symbol"] = sym

    try:
        await _cache.set(cache_key, json.dumps(result), ttl=_BT_CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass
    return result


@router.post("/{symbol}/journal")
async def journal_symbol(
    symbol: str = PathParam(..., description="Ticker symbol"),
    range: str = Query("1y"),
    horizon: int = Query(10, ge=1, le=60),
) -> Dict[str, Any]:
    """Compute the current read for ``symbol`` and log it as a tracked prediction.

    A 'none' read (no directional call) is returned but NOT stored, so the track
    record only contains real calls.
    """
    sym = _validate_symbol(symbol)
    days = _RANGE_DAYS.get(range.lower(), _RANGE_DAYS["1y"])
    try:
        read = await asyncio.to_thread(_compute_read, sym, days, range.lower())
    except Exception as e:  # noqa: BLE001
        logger.warning("crystal-ball journal[%s]: compute failed: %s", sym, e)
        raise HTTPException(status_code=502, detail="Crystal Ball data unavailable") from None
    if read is None:
        raise HTTPException(status_code=404, detail="No data for symbol")
    if read.get("_thin"):
        raise HTTPException(status_code=422, detail="Not enough price history for a read")
    entry = await asyncio.to_thread(_journal.record_prediction, read, horizon=horizon)
    return {"recorded": bool(entry.get("stored")), "entry": entry, "read": read}
