"""UDF (Universal Data Feed) — datafeed adapter for TradingView's Advanced Charts library.

Serves OHLCV history + symbol info from yfinance so the embedded pro charting library
renders off OUR data (not TradingView's). Endpoints follow TradingView's UDF spec:
  GET /api/udf/config | /symbols | /search | /history | /time
Real-time streaming is a later phase; history-only charts work fine to start.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, Query

udf_router = APIRouter(prefix="/api/udf", tags=["udf"])
logger = logging.getLogger("udf_routes")

# UDF resolution -> yfinance interval
_RES = {
    "1": "1m", "2": "2m", "5": "5m", "15": "15m", "30": "30m",
    "60": "60m", "1H": "60m", "120": "90m",
    "D": "1d", "1D": "1d", "W": "1wk", "1W": "1wk", "M": "1mo", "1M": "1mo",
}
SUPPORTED = ["1", "5", "15", "30", "60", "D", "W", "M"]


@udf_router.get("/config")
def config() -> Dict[str, Any]:
    return {
        "supported_resolutions": SUPPORTED,
        "supports_group_request": False,
        "supports_marks": False,
        "supports_search": True,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": [{"value": "", "name": "All Exchanges", "desc": ""}],
        "symbols_types": [{"name": "All types", "value": ""}, {"name": "Stock", "value": "stock"}],
    }


@udf_router.get("/time")
def server_time() -> int:
    return int(time.time())


@udf_router.get("/symbols")
def symbols(symbol: str) -> Dict[str, Any]:
    sym = symbol.upper().strip().split(":")[-1]   # tolerate EXCH:TICKER
    return {
        "name": sym, "ticker": sym, "full_name": sym, "description": sym, "type": "stock",
        "session": "0930-1600", "timezone": "America/New_York",
        "exchange": "", "listed_exchange": "",
        "minmov": 1, "pricescale": 100, "fractional": False,
        "has_intraday": True, "has_daily": True, "has_weekly_and_monthly": True,
        "supported_resolutions": SUPPORTED, "intraday_multipliers": ["1", "5", "15", "30", "60"],
        "volume_precision": 0, "data_status": "streaming" if False else "endofday",
    }


@udf_router.get("/search")
def search(query: str = "", limit: int = 30, type: str = "", exchange: str = "") -> List[Dict[str, Any]]:
    """Lightweight symbol search. v1 treats the query as a ticker; finnhub symbol
    search can be wired in later for fuzzy results."""
    q = query.upper().strip()
    if not q:
        return []
    return [{
        "symbol": q, "full_name": q, "description": q,
        "exchange": "", "ticker": q, "type": "stock",
    }][:limit]


@udf_router.get("/history")
def history(
    symbol: str,
    resolution: str,
    from_: int = Query(..., alias="from"),
    to: int = Query(...),
    countback: int = Query(None),
) -> Dict[str, Any]:
    """OHLCV bars in UDF format: {s, t[], o[], h[], l[], c[], v[]}."""
    import yfinance as yf

    sym = symbol.upper().strip().split(":")[-1]
    interval = _RES.get(resolution, "1d")
    start = dt.datetime.utcfromtimestamp(from_)
    end = dt.datetime.utcfromtimestamp(to) + dt.timedelta(days=1)  # inclusive of `to` day
    try:
        df = yf.Ticker(sym).history(start=start, end=end, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return {"s": "no_data", "nextTime": to}
        idx = [int(ts.timestamp()) for ts in df.index]
        out = {
            "s": "ok",
            "t": idx,
            "o": [round(float(x), 4) for x in df["Open"]],
            "h": [round(float(x), 4) for x in df["High"]],
            "l": [round(float(x), 4) for x in df["Low"]],
            "c": [round(float(x), 4) for x in df["Close"]],
            "v": [int(x) if x == x else 0 for x in df["Volume"]],  # NaN-safe
        }
        if countback and len(out["t"]) > countback:
            for k in ("t", "o", "h", "l", "c", "v"):
                out[k] = out[k][-countback:]
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("udf history failed for %s @ %s: %s", sym, resolution, e)
        return {"s": "error", "errmsg": str(e)[:200]}
