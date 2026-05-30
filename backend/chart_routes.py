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
