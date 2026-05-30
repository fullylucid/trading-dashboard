"""
Chart Routes - OHLCV candles, live-price relay, and on-demand AI TA reads.

This module backs the Phase-3 cockpit (TradingView Lightweight Charts). Three
surfaces, all guarded behind the existing agent-bridge session and mirroring the
patterns already in the codebase:

1. ``GET /api/chart/{symbol}``  -> OHLCV candles shaped for Lightweight Charts
   (``[{time, open, high, low, close, volume}]``). Reuses the cached adjusted
   OHLC pull (``scan_analytics._fetch_ohlcv`` -> ``hermes.charlotte.data_fetch``)
   and caches the marshalled payload briefly in Redis (``cache_manager``).

2. ``POST /api/chart/{symbol}/ai-read`` -> enqueues a read-only agent-bridge job
   (``kind="data"``) whose prompt is the symbol + its computed signals / S-R /
   Fibonacci levels, asking Claude for a concise TA thesis + key levels. Returns
   ``{job_id, conversation_id}`` so the frontend can stream the result over the
   existing ``/ws/agent`` channel (``chat:<conversation_id>``).

The live-price WebSocket endpoint (``/ws/prices``) itself is registered in
``main.py`` (like ``/ws/agent``); this module provides the ``FinnhubPriceRelay``
that bridges the existing Finnhub WS client into ``WebSocketManager`` so trades
fan out to subscribed browsers, plus the session/ticket auth reuse hooks.

Auth: the chart HTTP routes and the AI-read enqueue reuse ``agent_bridge``'s
signed session cookie; ``/ws/prices`` reuses the same short-lived WS ticket the
messenger uses. No new credential is introduced.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Path as PathParam, Query, Request

logger = logging.getLogger(__name__)

# Reuse the agent-bridge session + Redis bus rather than re-implementing auth.
# Imported lazily-safe at module load; if the bridge is unavailable the routes
# degrade to 503 instead of crashing import.
try:
    from agent_bridge import (
        require_session,
        _require_ready as _agent_redis,
        _append_turn,
        _touch_conversation,
        JOB_TTL,
        QUEUE_KEY,
    )
    HAS_AGENT_BRIDGE = True
except Exception as _ab_err:  # pragma: no cover - import-time guard
    HAS_AGENT_BRIDGE = False
    logger.warning(f"chart_routes: agent bridge unavailable ({_ab_err!r}); AI-read disabled")

import scan_analytics as _scan_analytics
from cache_manager import CacheManager

# ============================================================================
# Range / interval handling
# ============================================================================

# Map a requested range token -> trading days of history to fetch.
_RANGE_DAYS: Dict[str, int] = {
    "5d": 5,
    "1m": 31,
    "3m": 93,
    "6m": 186,
    "1y": 372,
    "2y": 740,
    "5y": 1830,
    "max": 1830,
}

# Lightweight Charts only renders what we hand it; interval is advisory here.
# We serve daily bars (the cached OHLC source is daily); intraday is a future
# extension. Accepted values are validated so the contract is explicit.
_VALID_INTERVALS = {"1d", "1day", "daily", "d"}

_cache = CacheManager()
_CHART_CACHE_TTL = 60  # seconds; brief, so live edges stay fresh


def _resolve_days(range_token: str) -> int:
    return _RANGE_DAYS.get(range_token.lower(), _RANGE_DAYS["1y"])


_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,14}$")


def _validate_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(s):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    return s


# ============================================================================
# OHLCV marshalling for Lightweight Charts
# ============================================================================

def _df_to_candles(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Marshal a fetch_ohlcv DataFrame into Lightweight-Charts candle dicts.

    ``time`` is a UNIX epoch-seconds integer (Lightweight Charts accepts that or
    a 'YYYY-MM-DD' business-day string; epoch is unambiguous across tz). Raw
    (unadjusted) OHLC is used for the visual candles so wicks line up with what a
    trader sees on a broker chart; volume is included for the histogram pane.
    """
    out: List[Dict[str, Any]] = []
    if df is None or len(df) == 0:
        return out

    has_vol = "Volume" in df.columns
    for idx, row in df.iterrows():
        try:
            ts = idx
            if isinstance(ts, (pd.Timestamp, datetime)):
                epoch = int(pd.Timestamp(ts).timestamp())
            else:
                epoch = int(pd.Timestamp(str(ts)).timestamp())
            o = float(row.get("Open"))
            h = float(row.get("High"))
            low = float(row.get("Low"))
            c = float(row.get("Close"))
            if not all(np.isfinite([o, h, low, c])):
                continue
            candle: Dict[str, Any] = {
                "time": epoch,
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(low, 4),
                "close": round(c, 4),
            }
            if has_vol:
                v = row.get("Volume")
                try:
                    vv = float(v)
                    candle["volume"] = int(vv) if np.isfinite(vv) else 0
                except (TypeError, ValueError):
                    candle["volume"] = 0
            out.append(candle)
        except (TypeError, ValueError):
            continue
    return out


# ============================================================================
# Fibonacci levels (anchored to the most recent significant swing)
# ============================================================================

_FIB_RETRACEMENTS = (0.236, 0.382, 0.5, 0.618, 0.786)
_FIB_EXTENSIONS = (1.272, 1.618)


def fibonacci_levels(
    high: "np.ndarray | List[float]",
    low: "np.ndarray | List[float]",
    close: "np.ndarray | List[float]",
    order: int = 5,
) -> Dict[str, Any]:
    """Auto-anchored Fibonacci retracement + extension levels.

    Anchors to the most recent confirmed swing high and swing low (strict local
    extrema with ``order`` confirming bars each side -> no look-ahead on the last
    ``order`` bars). Direction is inferred from which swing is more recent:

    - swing low after swing high  -> down-leg; retraces measured up from the low.
    - swing high after swing low   -> up-leg; retraces measured down from the high.

    Returns ``{direction, swing_high, swing_low, retracements{ratio:price},
    extensions{ratio:price}}`` or an all-``None`` skeleton when no swing pair is
    confirmable. Pure / deterministic; reuses the swing-pivot helpers from
    ``analytics.signals``.
    """
    skeleton: Dict[str, Any] = {
        "direction": None,
        "swing_high": None,
        "swing_low": None,
        "retracements": {},
        "extensions": {},
    }
    try:
        from analytics.signals import _local_max_idx, _local_min_idx  # type: ignore
    except Exception:  # pragma: no cover
        return skeleton

    h = np.asarray(high, dtype=float).ravel()
    l = np.asarray(low, dtype=float).ravel()
    if h.size != l.size or h.size < 2 * order + 1:
        return skeleton

    hi_idx = _local_max_idx(h, order)
    lo_idx = _local_min_idx(l, order)
    if hi_idx.size == 0 or lo_idx.size == 0:
        return skeleton

    last_hi_i = int(hi_idx[-1])
    last_lo_i = int(lo_idx[-1])
    swing_high = float(h[last_hi_i])
    swing_low = float(l[last_lo_i])
    if not (np.isfinite(swing_high) and np.isfinite(swing_low)) or swing_high <= swing_low:
        return skeleton

    span = swing_high - swing_low
    # More-recent pivot decides leg direction.
    direction = "down" if last_lo_i > last_hi_i else "up"

    retr: Dict[str, float] = {}
    ext: Dict[str, float] = {}
    for r in _FIB_RETRACEMENTS:
        # Retracement price measured back toward the prior extreme.
        price = swing_low + span * r if direction == "down" else swing_high - span * r
        retr[f"{r:.3f}"] = round(float(price), 4)
    for e in _FIB_EXTENSIONS:
        price = swing_low + span * e if direction == "down" else swing_high - span * e
        ext[f"{e:.3f}"] = round(float(price), 4)

    return {
        "direction": direction,
        "swing_high": round(swing_high, 4),
        "swing_low": round(swing_low, 4),
        "retracements": retr,
        "extensions": ext,
    }


# ============================================================================
# Server-computed indicator series + markers for the /full endpoint
# ============================================================================
#
# The /full endpoint enriches the raw candles with everything the frontend needs
# to render TradingView-style overlays/panes WITHOUT re-deriving any TA math in
# TypeScript. All indicator math is delegated to the tested ``analytics.signals``
# package (RSI/MACD series, divergence, support/resistance) — this layer only
# marshals already-fetched, COMPLETED-bar OHLC into time-keyed arrays and drops
# warm-up NaNs. Every sub-block is independently exception-wrapped: a failure in
# (say) the insider markers leaves the rest of the payload intact.
#
# No look-ahead: we compute on ``scan_analytics._completed(df)`` (the trailing,
# possibly-partial bar is dropped), exactly like the scan does.

# Per-bar MACD spans (mirror analytics.signals.macd defaults: 12/26/9).
_MACD_FAST, _MACD_SLOW, _MACD_SIGNAL = 12, 26, 9
_RSI_PERIOD = 14
_DIVERGENCE_LOOKBACK = 60
_RS_SERIES_BASELINE = 0.0  # rs line is rebased to 0% at the window's first bar


def _epochs_for_index(df: pd.DataFrame) -> List[int]:
    """UNIX epoch-seconds (int) for each row of ``df`` (DatetimeIndex assumed)."""
    epochs: List[int] = []
    for ts in df.index:
        try:
            if isinstance(ts, (pd.Timestamp, datetime)):
                epochs.append(int(pd.Timestamp(ts).timestamp()))
            else:
                epochs.append(int(pd.Timestamp(str(ts)).timestamp()))
        except (TypeError, ValueError):
            epochs.append(0)
    return epochs


def _series_to_points(
    epochs: List[int], values: "np.ndarray", nd: int = 4
) -> List[Dict[str, Any]]:
    """Zip epochs+values into ``[{time, value}]``, dropping NaN/inf warm-up bars."""
    pts: List[Dict[str, Any]] = []
    n = min(len(epochs), int(np.asarray(values).size))
    arr = np.asarray(values, dtype=float).ravel()
    for i in range(n):
        v = arr[i]
        if not np.isfinite(v) or epochs[i] == 0:
            continue
        pts.append({"time": epochs[i], "value": round(float(v), nd)})
    return pts


def _build_indicator_series(
    epochs: List[int], adj_close: "np.ndarray"
) -> Dict[str, Any]:
    """Per-bar RSI[] and MACD{macd,signal,hist}[] from the adjusted-close series.

    Reuses ``analytics.signals._rsi_series`` and replicates the package's MACD
    construction via its exported ``_ema`` so the per-bar values are identical to
    the single-value ``rsi``/``macd`` the scan reports for the latest bar. Warm-up
    NaNs are dropped. Returns ``{"rsi": [...], "macd": [...]}``; either may be
    empty on failure.
    """
    out: Dict[str, Any] = {"rsi": [], "macd": []}
    try:
        from analytics.signals import _rsi_series, _ema  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.debug(f"chart/full: indicator import failed: {e}")
        return out

    c = np.asarray(adj_close, dtype=float).ravel()

    # RSI series (Wilder).
    try:
        rsi_arr = _rsi_series(c, period=_RSI_PERIOD)
        out["rsi"] = _series_to_points(epochs, rsi_arr, nd=2)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full: rsi series failed: {e}")

    # MACD series (macd line, signal line, histogram) — one dict per bar.
    try:
        ema_fast = _ema(c, _MACD_FAST)
        ema_slow = _ema(c, _MACD_SLOW)
        macd_line = ema_fast - ema_slow
        signal_line = _ema(macd_line, _MACD_SIGNAL)
        hist = macd_line - signal_line
        macd_pts: List[Dict[str, Any]] = []
        n = min(len(epochs), macd_line.size)
        # MACD needs ``slow`` bars of warm-up; mask the leading region.
        warm = _MACD_SLOW - 1
        for i in range(n):
            if i < warm or epochs[i] == 0:
                continue
            mv, sv, hv = macd_line[i], signal_line[i], hist[i]
            if not (np.isfinite(mv) and np.isfinite(sv) and np.isfinite(hv)):
                continue
            macd_pts.append(
                {
                    "time": epochs[i],
                    "macd": round(float(mv), 4),
                    "signal": round(float(sv), 4),
                    "hist": round(float(hv), 4),
                }
            )
        out["macd"] = macd_pts
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full: macd series failed: {e}")

    return out


def _build_signal_markers(
    epochs: List[int], adj_close: "np.ndarray"
) -> List[Dict[str, Any]]:
    """Event markers: MACD signal-line crosses, MACD-zero crosses, RSI divergence.

    Each marker is ``{time, type, label}`` where ``type`` in
    ``{cross, divergence, breakout}``. Crosses are detected per-bar off the same
    MACD construction as the series; the divergence marker reuses the tested
    ``detect_divergence`` (RSI vs price) and is anchored to the most-recent
    confirmed price pivot inside the lookback window (no look-ahead). Best-effort.
    """
    markers: List[Dict[str, Any]] = []
    c = np.asarray(adj_close, dtype=float).ravel()
    try:
        from analytics.signals import _ema, _rsi_series, detect_divergence, _local_max_idx, _local_min_idx  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.debug(f"chart/full: marker import failed: {e}")
        return markers

    # --- MACD crosses ---
    try:
        ema_fast = _ema(c, _MACD_FAST)
        ema_slow = _ema(c, _MACD_SLOW)
        macd_line = ema_fast - ema_slow
        signal_line = _ema(macd_line, _MACD_SIGNAL)
        warm = _MACD_SLOW + _MACD_SIGNAL
        n = min(len(epochs), macd_line.size)
        for i in range(max(1, warm), n):
            if epochs[i] == 0:
                continue
            d_prev = macd_line[i - 1] - signal_line[i - 1]
            d_now = macd_line[i] - signal_line[i]
            if not (np.isfinite(d_prev) and np.isfinite(d_now)):
                continue
            if d_prev <= 0 < d_now:
                markers.append({"time": epochs[i], "type": "cross", "label": "MACD bullish cross"})
            elif d_prev >= 0 > d_now:
                markers.append({"time": epochs[i], "type": "cross", "label": "MACD bearish cross"})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full: macd cross markers failed: {e}")

    # --- RSI divergence (single, most-recent read anchored to last price pivot) ---
    try:
        rsi_arr = _rsi_series(c, period=_RSI_PERIOD)
        div = detect_divergence(c, rsi_arr, lookback=_DIVERGENCE_LOOKBACK)
        label = div.get("signal")
        if label:
            # Anchor the marker at the most-recent confirmed price pivot in window.
            win = min(_DIVERGENCE_LOOKBACK, c.size)
            base = c.size - win
            sub = c[-win:]
            if label == "bearish":
                idxs = _local_max_idx(sub, 3)
            else:
                idxs = _local_min_idx(sub, 3)
            if idxs.size:
                anchor = base + int(idxs[-1])
                if 0 <= anchor < len(epochs) and epochs[anchor]:
                    markers.append(
                        {
                            "time": epochs[anchor],
                            "type": "divergence",
                            "label": f"{label} RSI divergence",
                        }
                    )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full: divergence marker failed: {e}")

    markers.sort(key=lambda m: m["time"])
    return markers


def _build_insider_markers(sym: str) -> List[Dict[str, Any]]:
    """Insider open-market-buy cluster markers ``[{time, label}]`` from EDGAR.

    Reuses ``scan_analytics._fetch_insider_block`` (Form-4 -> open-market buys ->
    clusters -> score), which is per-process cached and never raises. We surface
    the strongest cluster's window (``start_date``) as a single dated marker so
    the chart can flag insider accumulation. Returns ``[]`` when there's no
    cluster or insider data is unavailable.
    """
    out: List[Dict[str, Any]] = []
    try:
        block = _scan_analytics._fetch_insider_block(sym)
        if not block or not block.get("has_cluster"):
            return out
        start = block.get("start_date") or block.get("end_date")
        if not start:
            return out
        try:
            epoch = int(pd.Timestamp(str(start)).timestamp())
        except (TypeError, ValueError):
            return out
        n_ins = block.get("num_insiders")
        bucket = block.get("bucket")
        label = f"Insider cluster buy ({n_ins} insiders)" if n_ins else "Insider cluster buy"
        if bucket:
            label = f"{label} [{bucket}]"
        out.append({"time": epoch, "label": label})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full[{sym}]: insider markers failed: {e}")
    return out


def _build_rs_vs_spy_series(
    epochs: List[int], adj_close: "np.ndarray", spy_close: Optional[pd.Series]
) -> List[Dict[str, Any]]:
    """Relative-strength line vs SPY, rebased to 0% at the window start.

    For each bar we plot the cumulative outperformance of the symbol vs SPY:
    ``(asset_t/asset_0 - 1) - (spy_t/spy_0 - 1)`` in percentage points, aligned on
    the trailing ``len(epochs)`` bars. This is the per-bar, render-ready cousin of
    the scan's scalar ``relative_strength`` (which uses ``roc`` differences).
    Returns ``[{time, value}]`` (value = pct points) or ``[]`` if SPY is missing.
    """
    if spy_close is None:
        return []
    try:
        asset = np.asarray(adj_close, dtype=float).ravel()
        spy = pd.to_numeric(spy_close, errors="coerce").to_numpy(dtype=float).ravel()
        n = min(len(epochs), asset.size, spy.size)
        if n < 2:
            return []
        a = asset[-n:]
        s = spy[-n:]
        ep = epochs[-n:]
        a0 = a[0]
        s0 = s[0]
        if not (np.isfinite(a0) and np.isfinite(s0)) or a0 == 0 or s0 == 0:
            return []
        pts: List[Dict[str, Any]] = []
        for i in range(n):
            if not (np.isfinite(a[i]) and np.isfinite(s[i])) or ep[i] == 0:
                continue
            rs = ((a[i] / a0 - 1.0) - (s[i] / s0 - 1.0)) * 100.0
            pts.append({"time": ep[i], "value": round(float(rs), 3)})
        return pts
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full: rs-vs-spy series failed: {e}")
        return []


def _current_confluence(sym: str, df: pd.DataFrame, adj: pd.Series, spy_close: Optional[pd.Series]) -> Optional[Dict[str, Any]]:
    """Single current confluence summary (NOT per-bar — too heavy to score every bar).

    Reuses the scan's ``_build_signals_block`` + ``_fetch_insider_block`` +
    ``sector_rotation_tags`` and folds them through the tested ``analytics.alerts``
    scorer (the same fusion the portfolio scan uses), yielding one
    ``{confidence, bucket, reason, direction, ...}`` for the latest completed bar.

    Per-bar full alert scoring is deliberately avoided: the alert scorer fuses
    insider/sector/regime context that is only meaningful "as of now", and
    re-running it for every historical bar would be both look-ahead-leaky and
    expensive. The per-bar RSI/MACD series + event markers carry the historical
    signal; this carries the live confluence read.
    """
    try:
        signals = _scan_analytics._build_signals_block(sym, df, adj, spy_close=spy_close)
    except Exception:  # noqa: BLE001
        signals = {}
    insider: Dict[str, Any] = {}
    try:
        insider = _scan_analytics._fetch_insider_block(sym) or {}
    except Exception:  # noqa: BLE001
        insider = {}
    sector = None
    try:
        sector = (_scan_analytics.sector_rotation_tags([sym]) or {}).get(sym)
    except Exception:  # noqa: BLE001
        sector = None
    try:
        from analytics.alerts import score_alert  # type: ignore
        alert = score_alert(
            symbol=sym,
            signals=signals or {},
            insider=insider or {},
            regime=None,
            risk={},
            sector_rotation=sector,
            composite_score=None,
        )
        return alert
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full[{sym}]: confluence failed: {e}")
        return None


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/chart", tags=["chart"])


@router.get("/{symbol}")
async def get_chart(
    request: Request,
    symbol: str = PathParam(..., description="Ticker symbol"),
    range: str = Query("1y", description="5d|1m|3m|6m|1y|2y|5y|max"),
    interval: str = Query("1d", description="Bar interval (daily only for now)"),
) -> Dict[str, Any]:
    """OHLCV candles for Lightweight Charts.

    Returns ``{symbol, range, interval, candles: [{time, open, high, low,
    close, volume}], count}``. Behind the agent-bridge session. Exception-wrapped:
    any data-source failure surfaces as a 502 with no leaked internals.
    """
    if not HAS_AGENT_BRIDGE:
        raise HTTPException(status_code=503, detail="Chart routes unavailable")
    require_session(request)

    sym = _validate_symbol(symbol)
    if interval.lower() not in _VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Unsupported interval (daily only)")
    days = _resolve_days(range)

    cache_key = f"chart:{sym}:{days}:d"
    cached = await _cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    try:
        # Reuse the cached adjusted OHLC pull. Run the (sync, possibly IO-bound)
        # fetch off the event loop so we never block other requests.
        df = await asyncio.to_thread(_scan_analytics._fetch_ohlcv, sym, days)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chart[{sym}]: fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Chart data unavailable") from None

    if df is None or len(df) == 0:
        raise HTTPException(status_code=404, detail="No chart data for symbol")

    candles = _df_to_candles(df)
    payload = {
        "symbol": sym,
        "range": range.lower(),
        "interval": "1d",
        "candles": candles,
        "count": len(candles),
    }
    try:
        await _cache.set(cache_key, json.dumps(payload), ttl=_CHART_CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass
    return payload


@router.get("/{symbol}/full")
async def get_chart_full(
    request: Request,
    symbol: str = PathParam(..., description="Ticker symbol"),
    range: str = Query("1y", description="5d|1m|3m|6m|1y|2y|5y|max"),
    interval: str = Query("1d", description="Bar interval (daily only for now)"),
) -> Dict[str, Any]:
    """Server-enriched chart payload so the frontend is pure rendering.

    Returns the same candles as ``GET /{symbol}`` PLUS server-computed (all reusing
    the tested ``analytics`` package, completed-bars only, no look-ahead):

    - ``overlays`` : ``{fib_levels, support_resistance}``
    - ``indicators`` : ``{rsi: [{time,value}], macd: [{time,macd,signal,hist}]}``
    - ``markers`` : ``{signal_events: [{time,type,label}], insider_buys: [{time,label}]}``
    - ``rs_vs_spy`` : ``[{time, value}]`` (cumulative % outperformance vs SPY)
    - ``context`` : ``{regime, sector_rotation}`` (sector read for this symbol)
    - ``confluence`` : single CURRENT alert summary (per-bar scoring is intentionally
      skipped as too heavy / look-ahead-leaky — see ``_current_confluence``).

    Every sub-block is independently optional: a failure in one leaves the rest of
    the payload intact (the offending key is omitted or empty, with a note in
    ``data_gaps``). Reuses the cached ``_fetch_ohlcv``; behind the session.
    """
    if not HAS_AGENT_BRIDGE:
        raise HTTPException(status_code=503, detail="Chart routes unavailable")
    require_session(request)

    sym = _validate_symbol(symbol)
    if interval.lower() not in _VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Unsupported interval (daily only)")
    days = _resolve_days(range)

    cache_key = f"chartfull:{sym}:{days}:d"
    cached = await _cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    def _compute() -> Dict[str, Any]:
        """All sync, IO-bound work — run off the event loop in one thread hop."""
        data_gaps: List[str] = []
        raw = _scan_analytics._fetch_ohlcv(sym, days)
        if raw is None or len(raw) == 0:
            return {"_empty": True}

        # Visual candles use the RAW (through-now) frame so the live edge shows;
        # all TA is computed on COMPLETED bars only (drop the trailing partial).
        candles = _df_to_candles(raw)
        cdf = _scan_analytics._completed(raw)
        if cdf is None:
            return {
                "candles": candles,
                "indicators": {"rsi": [], "macd": []},
                "overlays": {},
                "markers": {"signal_events": [], "insider_buys": []},
                "rs_vs_spy": [],
                "context": {},
                "confluence": None,
                "data_gaps": ["completed_bars_unavailable"],
            }

        epochs = _epochs_for_index(cdf)
        adj = _scan_analytics._adj_close(cdf)
        adj_arr = adj.to_numpy(dtype=float) if adj is not None else np.asarray([])

        # SPY (completed) once, reused for rs line + signals + regime.
        spy_close: Optional[pd.Series] = None
        try:
            spy_df = _scan_analytics._completed(_scan_analytics._fetch_ohlcv(_scan_analytics._BENCHMARK, days))
            if spy_df is not None:
                spy_close = _scan_analytics._adj_close(spy_df)
        except Exception:  # noqa: BLE001
            data_gaps.append("spy_unavailable")

        # --- Overlays (fib + S/R) from raw OHLC swings ---
        overlays: Dict[str, Any] = {}
        try:
            from analytics.signals import support_resistance  # type: ignore
            high = pd.to_numeric(cdf["High"], errors="coerce").to_numpy(dtype=float)
            low = pd.to_numeric(cdf["Low"], errors="coerce").to_numpy(dtype=float)
            close = pd.to_numeric(cdf["Close"], errors="coerce").to_numpy(dtype=float)
            overlays["fib_levels"] = fibonacci_levels(high, low, close)
            overlays["support_resistance"] = support_resistance(high, low, close)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"chart/full[{sym}]: overlays failed: {e}")
            data_gaps.append("overlays_failed")

        # --- Indicator series ---
        if adj is not None and adj_arr.size:
            indicators = _build_indicator_series(epochs, adj_arr)
        else:
            indicators = {"rsi": [], "macd": []}
            data_gaps.append("adj_close_unavailable")

        # --- Markers ---
        signal_events: List[Dict[str, Any]] = []
        if adj is not None and adj_arr.size:
            signal_events = _build_signal_markers(epochs, adj_arr)
        insider_buys = _build_insider_markers(sym)

        # --- Relative-strength line vs SPY ---
        rs_line: List[Dict[str, Any]] = []
        if adj is not None and adj_arr.size:
            rs_line = _build_rs_vs_spy_series(epochs, adj_arr, spy_close)

        # --- Confluence (single current read) ---
        confluence = None
        if adj is not None and adj_arr.size:
            confluence = _current_confluence(sym, cdf, adj, spy_close)

        return {
            "candles": candles,
            "indicators": indicators,
            "overlays": overlays,
            "markers": {"signal_events": signal_events, "insider_buys": insider_buys},
            "rs_vs_spy": rs_line,
            "spy_close": spy_close,  # passed out for the async regime/context step
            "confluence": confluence,
            "data_gaps": data_gaps,
        }

    try:
        computed = await asyncio.to_thread(_compute)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chart/full[{sym}]: compute failed: {e}")
        raise HTTPException(status_code=502, detail="Chart data unavailable") from None

    if computed.get("_empty"):
        raise HTTPException(status_code=404, detail="No chart data for symbol")

    # --- Context: regime (async) + sector rotation for this symbol ---
    spy_close = computed.pop("spy_close", None)
    context: Dict[str, Any] = {}
    try:
        context["regime"] = await _scan_analytics.regime_block(spy_close)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full[{sym}]: regime failed: {e}")
        context["regime"] = None
    try:
        context["sector_rotation"] = (
            await asyncio.to_thread(_scan_analytics.sector_rotation_tags, [sym])
        ).get(sym)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chart/full[{sym}]: sector rotation failed: {e}")
        context["sector_rotation"] = None

    payload: Dict[str, Any] = {
        "symbol": sym,
        "range": range.lower(),
        "interval": "1d",
        "count": len(computed.get("candles") or []),
        "candles": computed.get("candles") or [],
        "indicators": computed.get("indicators") or {"rsi": [], "macd": []},
        "overlays": computed.get("overlays") or {},
        "markers": computed.get("markers") or {"signal_events": [], "insider_buys": []},
        "rs_vs_spy": computed.get("rs_vs_spy") or [],
        "context": context,
        "confluence": computed.get("confluence"),
        "data_gaps": computed.get("data_gaps") or [],
    }
    try:
        await _cache.set(cache_key, json.dumps(payload), ttl=_CHART_CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass
    return payload


@router.get("/portfolio")
async def get_chart_portfolio(
    request: Request,
    range: str = Query("1y", description="5d|1m|3m|6m|1y|2y|5y|max"),
) -> Dict[str, Any]:
    """Portfolio-weighted, normalized equity/return series for the 'whole portfolio' view.

    Builds one blended return line from CURRENT SnapTrade holdings: each holding's
    adjusted-return series (completed bars) is weighted by its live portfolio
    weight (``market_value`` share) and summed bar-by-bar. The result is presented
    two ways on a common, intersected trading-day axis:

    - ``equity`` : ``[{time, value}]`` growth of $1 (index = 1.0 at window start)
    - ``returns``: ``[{time, value}]`` cumulative % return rebased to 0% at start

    Reuses ``snaptrade_portfolio.get_portfolio_instance`` (weights) and the cached
    ``_fetch_ohlcv``. Degrades gracefully: names with no OHLC are dropped (and
    listed in ``skipped``), weights are renormalized over the survivors, and an
    empty book yields empty series rather than an error. Behind the session.
    """
    if not HAS_AGENT_BRIDGE:
        raise HTTPException(status_code=503, detail="Chart routes unavailable")
    require_session(request)

    days = _resolve_days(range)

    cache_key = f"chartportfolio:{days}:d"
    cached = await _cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    # --- Pull current holdings + weights (SnapTrade is source of truth). ---
    try:
        from snaptrade_portfolio import get_portfolio_instance  # type: ignore
        portfolio = await get_portfolio_instance()
        pdata = await portfolio.get_portfolio()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chart/portfolio: holdings unavailable: {e}")
        raise HTTPException(status_code=502, detail="Portfolio data unavailable") from None

    positions = (pdata or {}).get("positions") or []
    # Aggregate weights by symbol (a symbol can appear across multiple accounts).
    weights: Dict[str, float] = {}
    for p in positions:
        sym = (p.get("symbol") or "").strip().upper()
        if not sym or sym == "?":
            continue
        try:
            mv = float(p.get("market_value") or 0.0)
        except (TypeError, ValueError):
            mv = 0.0
        if mv <= 0:
            continue
        weights[sym] = weights.get(sym, 0.0) + mv
    total_mv = sum(weights.values())
    if not weights or total_mv <= 0:
        empty = {
            "range": range.lower(),
            "interval": "1d",
            "equity": [],
            "returns": [],
            "holdings": [],
            "skipped": [],
            "count": 0,
            "note": "no_holdings",
        }
        return empty
    for s in list(weights.keys()):
        weights[s] = weights[s] / total_mv

    def _compute_portfolio() -> Dict[str, Any]:
        """Sync: fetch each holding's returns, weight-blend on a common axis."""
        ret_series: Dict[str, pd.Series] = {}
        skipped: List[str] = []
        for sym in weights:
            try:
                cdf = _scan_analytics._completed(_scan_analytics._fetch_ohlcv(sym, days))
                if cdf is None:
                    skipped.append(sym)
                    continue
                adj = _scan_analytics._adj_close(cdf)
                if adj is None or len(adj) < 2:
                    skipped.append(sym)
                    continue
                ret_series[sym] = adj.pct_change()
            except Exception:  # noqa: BLE001
                skipped.append(sym)

        if not ret_series:
            return {"equity": [], "returns": [], "skipped": skipped, "used": []}

        # Renormalize weights over the survivors.
        used = list(ret_series.keys())
        surv_total = sum(weights[s] for s in used) or 1.0
        norm_w = {s: weights[s] / surv_total for s in used}

        # Align on the intersection of trading days (inner join), drop warm-up NaNs.
        rets_df = pd.DataFrame(ret_series).dropna(how="any")
        if rets_df.empty:
            return {"equity": [], "returns": [], "skipped": skipped, "used": used}

        w_vec = pd.Series(norm_w)
        port_ret = (rets_df[used] * w_vec[used]).sum(axis=1)

        equity = (1.0 + port_ret).cumprod()
        cum_ret_pct = (equity - 1.0) * 100.0

        eq_pts: List[Dict[str, Any]] = []
        rp_pts: List[Dict[str, Any]] = []
        for ts, ev in equity.items():
            try:
                epoch = int(pd.Timestamp(ts).timestamp())
            except (TypeError, ValueError):
                continue
            if not np.isfinite(ev):
                continue
            eq_pts.append({"time": epoch, "value": round(float(ev), 6)})
            rp = cum_ret_pct.loc[ts]
            rp_pts.append({"time": epoch, "value": round(float(rp), 4)})

        return {
            "equity": eq_pts,
            "returns": rp_pts,
            "skipped": skipped,
            "used": used,
            "weights_used": {s: round(norm_w[s], 6) for s in used},
        }

    try:
        result = await asyncio.to_thread(_compute_portfolio)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chart/portfolio: compute failed: {e}")
        raise HTTPException(status_code=502, detail="Portfolio series unavailable") from None

    used = result.get("used") or []
    payload = {
        "range": range.lower(),
        "interval": "1d",
        "equity": result.get("equity") or [],
        "returns": result.get("returns") or [],
        "holdings": [
            {"symbol": s, "weight": round(weights.get(s, 0.0), 6)} for s in used
        ],
        "weights_used": result.get("weights_used") or {},
        "skipped": result.get("skipped") or [],
        "count": len(result.get("equity") or []),
    }
    try:
        await _cache.set(cache_key, json.dumps(payload), ttl=_CHART_CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass
    return payload


# ----------------------------------------------------------------------------
# On-demand AI TA read
# ----------------------------------------------------------------------------

def _round_opt(x: Any, nd: int = 2) -> Optional[float]:
    try:
        xv = float(x)
        return round(xv, nd) if np.isfinite(xv) else None
    except (TypeError, ValueError):
        return None


def _build_ta_context(sym: str) -> Dict[str, Any]:
    """Compute the signal / S-R / Fibonacci context for the AI-read prompt.

    Best-effort and fully exception-wrapped: returns whatever it can, with a
    ``data_gaps`` note for anything missing. Reuses the same completed-bar
    adjusted-OHLC discipline as the scan (no look-ahead).
    """
    ctx: Dict[str, Any] = {"symbol": sym, "data_gaps": []}
    try:
        raw = _scan_analytics._fetch_ohlcv(sym)
        df = _scan_analytics._completed(raw)
        if df is None:
            ctx["data_gaps"].append("ohlc_unavailable")
            return ctx
        adj = _scan_analytics._adj_close(df)
        if adj is None:
            ctx["data_gaps"].append("adj_close_unavailable")
            return ctx

        ctx["last_close"] = _round_opt(adj.iloc[-1], 4)

        # SPY for relative strength (once-fetched, completed bars).
        spy_close = None
        try:
            spy_df = _scan_analytics._completed(
                _scan_analytics._fetch_ohlcv(_scan_analytics._BENCHMARK)
            )
            if spy_df is not None:
                spy_close = _scan_analytics._adj_close(spy_df)
        except Exception:  # noqa: BLE001
            pass

        # Reuse the scan's signal marshaller for a consistent shape.
        try:
            ctx["signals"] = _scan_analytics._build_signals_block(
                sym, df, adj, spy_close=spy_close
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"ai-read[{sym}]: signals failed: {e}")
            ctx["data_gaps"].append("signals_failed")

        # Support / resistance + Fibonacci from raw OHLC swings.
        try:
            from analytics.signals import support_resistance  # type: ignore
            high = pd.to_numeric(df["High"], errors="coerce").to_numpy(dtype=float)
            low = pd.to_numeric(df["Low"], errors="coerce").to_numpy(dtype=float)
            close = pd.to_numeric(df["Close"], errors="coerce").to_numpy(dtype=float)
            ctx["support_resistance"] = support_resistance(high, low, close)
            ctx["fibonacci"] = fibonacci_levels(high, low, close)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"ai-read[{sym}]: S-R/fib failed: {e}")
            ctx["data_gaps"].append("levels_failed")

    except Exception as e:  # noqa: BLE001
        logger.warning(f"ai-read[{sym}]: context build failed: {e}")
        ctx["data_gaps"].append("context_error")
    return ctx


def _render_ai_prompt(ctx: Dict[str, Any]) -> str:
    """Turn the computed context into a concise, read-only TA-thesis prompt."""
    sym = ctx.get("symbol", "?")
    blob = json.dumps(ctx, default=str, separators=(",", ":"))
    return (
        f"Read-only technical analysis for {sym}. You are given precomputed, "
        f"no-look-ahead signals, support/resistance, and Fibonacci levels (JSON "
        f"below). Do NOT fetch data or run tools — reason only from this context.\n\n"
        f"Write a concise TA thesis (4-7 sentences): current trend/regime read, "
        f"momentum (RSI/MACD/divergence), relative strength vs SPY, and where price "
        f"sits in its range. Then list the KEY LEVELS to watch (nearest support, "
        f"nearest resistance, and the most relevant Fibonacci levels) as a short "
        f"bulleted list with prices. Flag anything in data_gaps as a caveat. End with "
        f"a one-line bias (bullish / neutral / bearish) and the invalidation level.\n\n"
        f"CONTEXT JSON:\n{blob}"
    )


@router.post("/{symbol}/ai-read")
async def ai_read(
    request: Request,
    symbol: str = PathParam(..., description="Ticker symbol"),
    conversation_id: Optional[str] = Query(
        None, description="Existing conversation to append to; created if absent"
    ),
) -> Dict[str, Any]:
    """Enqueue a read-only ('data' kind) agent-bridge job for a TA read.

    Computes the symbol's signals / S-R / Fibonacci context, renders a prompt,
    and pushes a job onto the same Redis queue the messenger uses. Returns
    ``{job_id, conversation_id, status}`` so the frontend can stream the result
    over ``/ws/agent`` (channel ``chat:<conversation_id>``). Fully behind the
    session; exception-wrapped.
    """
    if not HAS_AGENT_BRIDGE:
        raise HTTPException(status_code=503, detail="AI read unavailable")
    require_session(request)
    sym = _validate_symbol(symbol)
    r = _agent_redis()

    # Build context off the event loop (sync IO-bound fetches).
    try:
        ctx = await asyncio.to_thread(_build_ta_context, sym)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"ai-read[{sym}]: context error: {e}")
        ctx = {"symbol": sym, "data_gaps": ["context_error"]}

    prompt = _render_ai_prompt(ctx)

    # Resolve / create the conversation so the FE can subscribe immediately.
    conv_id = conversation_id or str(uuid.uuid4())
    if not conversation_id:
        try:
            await r.hset(
                f"agent:conv:{conv_id}:meta",
                mapping={
                    "title": f"AI TA read: {sym}",
                    "created_at": datetime.utcnow().isoformat() + "Z",
                },
            )
            await _touch_conversation(r, conv_id)
        except Exception as e:  # noqa: BLE001
            logger.error(f"ai-read[{sym}]: conv create failed: {e}")
            raise HTTPException(status_code=503, detail="Bus unavailable") from None

    job_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat() + "Z"
    existing = await r.llen(f"agent:conv:{conv_id}")
    resume_session = await r.hget(f"agent:conv:{conv_id}:meta", "claude_session_id")

    job = {
        "job_id": job_id,
        "kind": "data",  # read-only: worker must not branch/PR
        "content": prompt,
        "conversation_id": conv_id,
        "created_at": created_at,
        "needs_title": existing == 0,
        "resume_session": resume_session,
        "source": "ai-read",
        "symbol": sym,
    }
    try:
        await r.hset(
            f"agent:job:{job_id}",
            mapping={
                "status": "queued",
                "kind": "data",
                "created_at": created_at,
                "conversation_id": conv_id,
            },
        )
        await r.expire(f"agent:job:{job_id}", JOB_TTL)
        await _append_turn(
            r,
            conv_id,
            {
                "role": "user",
                "content": f"[AI TA read requested for {sym}]",
                "job_id": job_id,
                "ts": created_at,
            },
        )
        await r.rpush(QUEUE_KEY, json.dumps(job))
    except Exception as e:  # noqa: BLE001
        logger.error(f"ai-read[{sym}]: enqueue failed: {e}")
        raise HTTPException(status_code=503, detail="Enqueue failed") from None

    return {"job_id": job_id, "conversation_id": conv_id, "status": "queued"}


# ============================================================================
# Live-price relay (Finnhub WS -> WebSocketManager -> browser)
# ============================================================================

class FinnhubPriceRelay:
    """Bridge the Finnhub trade WebSocket into the shared WebSocketManager.

    One upstream Finnhub connection multiplexes every browser. The relay tracks a
    refcount per symbol so it only ``subscribe``/``unsubscribe`` upstream when the
    first/last interested browser appears/leaves, and fans each trade out via
    ``ws_manager.broadcast_price_update`` (which already routes by per-client
    subscription). Auto-reconnects with backoff. Never raises into callers.
    """

    FINNHUB_WS_URL = "wss://ws.finnhub.io?token={token}"

    def __init__(self, api_key: str, ws_manager) -> None:
        self._api_key = api_key
        self._ws_manager = ws_manager
        self._symbol_refs: Dict[str, int] = {}
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._stop = False

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    async def start(self) -> None:
        if not self.enabled:
            logger.warning("FinnhubPriceRelay: no FINNHUB_API_KEY; live prices disabled")
            return
        if self._task is None or self._task.done():
            self._stop = False
            self._task = asyncio.create_task(self._run())
            logger.info("FinnhubPriceRelay: started")

    async def stop(self) -> None:
        self._stop = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def subscribe(self, symbols: List[str]) -> None:
        """Add browser interest in symbols; subscribe upstream on first ref."""
        async with self._lock:
            for raw in symbols:
                sym = (raw or "").strip().upper()
                if not sym:
                    continue
                first = self._symbol_refs.get(sym, 0) == 0
                self._symbol_refs[sym] = self._symbol_refs.get(sym, 0) + 1
                if first:
                    await self._send_upstream({"type": "subscribe", "symbol": sym})

    async def unsubscribe(self, symbols: List[str]) -> None:
        """Drop browser interest; unsubscribe upstream when refcount hits zero."""
        async with self._lock:
            for raw in symbols:
                sym = (raw or "").strip().upper()
                if not sym or sym not in self._symbol_refs:
                    continue
                self._symbol_refs[sym] -= 1
                if self._symbol_refs[sym] <= 0:
                    del self._symbol_refs[sym]
                    await self._send_upstream({"type": "unsubscribe", "symbol": sym})

    async def _send_upstream(self, msg: Dict[str, Any]) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"FinnhubPriceRelay: upstream send failed: {e}")

    async def _resubscribe_all(self) -> None:
        """Re-issue every active subscription after a (re)connect."""
        async with self._lock:
            for sym in list(self._symbol_refs.keys()):
                await self._send_upstream({"type": "subscribe", "symbol": sym})

    async def _run(self) -> None:
        import websockets  # local import; matches data_fetcher

        backoff = 1.0
        while not self._stop:
            try:
                async with websockets.connect(
                    self.FINNHUB_WS_URL.format(token=self._api_key)
                ) as ws:
                    self._ws = ws
                    backoff = 1.0
                    logger.info("FinnhubPriceRelay: connected upstream")
                    await self._resubscribe_all()
                    async for message in ws:
                        try:
                            data = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if data.get("type") != "trade":
                            continue
                        await self._fan_out(data.get("data", []))
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning(f"FinnhubPriceRelay: upstream error: {e}")
            finally:
                self._ws = None
            if self._stop:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _fan_out(self, trades: List[Dict[str, Any]]) -> None:
        if self._ws_manager is None:
            return
        # Collapse to the latest trade per symbol in this frame.
        latest: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            sym = t.get("s")
            if not sym:
                continue
            latest[sym] = t
        for sym, t in latest.items():
            price_data = {
                "symbol": sym,
                "price": t.get("p"),
                "volume": t.get("v"),
                "timestamp": (
                    datetime.utcfromtimestamp(t.get("t", 0) / 1000).isoformat()
                    if t.get("t")
                    else datetime.utcnow().isoformat()
                ),
                "conditions": t.get("c"),
            }
            try:
                await self._ws_manager.broadcast_price_update(sym, price_data)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"FinnhubPriceRelay: broadcast failed for {sym}: {e}")
