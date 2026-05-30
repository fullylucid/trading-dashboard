"""
Portfolio API Routes
FastAPI endpoints for brokerage portfolio tracking and display.

Backed by SnapTrade (OAuth) — see snaptrade_portfolio.py. The legacy
robinhood_portfolio.py remains in the tree as a fallback but is no
longer wired up.
"""

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any, Tuple, Callable
import asyncio
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone

try:
    # Py3.9+: zoneinfo in stdlib
    from zoneinfo import ZoneInfo
    _PT_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tzdata missing
    _PT_TZ = timezone(timedelta(hours=-8))

from snaptrade_portfolio import get_portfolio_instance, clear_portfolio_cache
from deep_dive_routes import _run_deep_dive, _generate_thesis, THESIS_MODEL

# Additive analytics layer (Phase 1). Import is best-effort so the scan still
# runs if the analytics package is unavailable for any reason.
try:
    import scan_analytics as _scan_analytics
except Exception:  # pragma: no cover
    try:
        from backend import scan_analytics as _scan_analytics  # type: ignore
    except Exception:
        _scan_analytics = None

logger = logging.getLogger(__name__)

# Create router
portfolio_router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@portfolio_router.get("/")
async def get_portfolio(
    refresh: bool = Query(False, description="Force refresh from Robinhood")
) -> Dict[str, Any]:
    """
    Get complete portfolio summary
    
    Returns:
        - account_value: Total portfolio value
        - buying_power: Available cash to invest
        - cash: Cash in account
        - positions: List of open positions with P&L
        - watchlist: Watchlist items
        - summary: Portfolio statistics
    """
    try:
        if refresh:
            await clear_portfolio_cache()
        
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_portfolio()
        
        return {
            "success": "error" not in data,
            "data": data,
        }
    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/summary")
async def get_portfolio_summary() -> Dict[str, Any]:
    """Get portfolio summary (high-level overview)"""
    try:
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_portfolio()
        
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])
        
        summary = data.get("summary", {})
        accounts = data.get("accounts", [])
        margin_debit = sum(abs(acc["cash"]) for acc in accounts if acc["cash"] < 0)
        gross_market_value = sum(acc["market_value"] for acc in accounts)
        
        return {
            "total_value": data.get("account_value", 0),
            "buying_power": data.get("buying_power", 0),
            "cash": data.get("cash", 0),
            "positions_count": summary.get("total_positions", 0),
            "total_gain_loss": summary.get("total_gain_loss", 0),
            "total_gain_loss_pct": summary.get("total_gain_loss_pct", 0),
            "top_position": summary.get("top_position"),
            "timestamp": data.get("timestamp"),
            "margin_debit": margin_debit,
            "gross_market_value": gross_market_value,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching portfolio summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/positions")
async def get_positions(
    limit: int = Query(50, ge=1, le=500, description="Max positions to return"),
    sort_by: str = Query("value", regex="^(value|gain_loss|gain_loss_pct|symbol)$")
) -> List[Dict[str, Any]]:
    """
    Get all open positions
    
    Query params:
        - limit: Maximum positions to return
        - sort_by: Sort field (value, gain_loss, gain_loss_pct, symbol)
    
    Returns list of positions with:
        - symbol, quantity, current_price, average_buy_price
        - current_value, cost_basis, gain_loss, gain_loss_pct
        - bid_price, ask_price, pe_ratio, market_cap
    """
    try:
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_portfolio()
        
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])
        
        positions = data.get("positions", [])[:limit]
        
        # Sort
        sort_map = {
            "value": lambda x: x["current_value"],
            "gain_loss": lambda x: x["gain_loss"],
            "gain_loss_pct": lambda x: x["gain_loss_pct"],
            "symbol": lambda x: x["symbol"],
        }
        
        if sort_by in sort_map:
            positions = sorted(positions, key=sort_map[sort_by], reverse=(sort_by != "symbol"))
        
        return positions
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/position/{symbol}")
async def get_position(symbol: str) -> Dict[str, Any]:
    """Get specific position details by symbol"""
    try:
        portfolio = await get_portfolio_instance()
        position = await portfolio.get_position(symbol.upper())
        
        if not position:
            raise HTTPException(status_code=404, detail=f"Position {symbol} not found")
        
        return position
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching position {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/watchlist")
async def get_watchlist() -> List[Dict[str, Any]]:
    """Get watchlist items with current prices"""
    try:
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_portfolio()
        
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])
        
        return data.get("watchlist", [])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/performance")
async def get_performance(
    days: int = Query(30, ge=1, le=365, description="Days of history to retrieve")
) -> Dict[str, Any]:
    """
    Get portfolio performance/trading history
    
    Returns:
        - recent_orders: Last 20 orders
        - buy_orders: Count of buy orders
        - sell_orders: Count of sell orders
    """
    try:
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_performance(days=days)
        
        return {
            "period_days": days,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error fetching performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.post("/refresh")
async def refresh_portfolio() -> Dict[str, str]:
    """Force refresh portfolio data from Robinhood"""
    try:
        await clear_portfolio_cache()
        return {"status": "success", "message": "Portfolio cache cleared, will refresh on next request"}
    except Exception as e:
        logger.error(f"Error refreshing portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/holdings-breakdown")
async def get_holdings_breakdown() -> Dict[str, Any]:
    """
    Get portfolio allocation breakdown
    Includes sector, position size, concentration
    """
    try:
        portfolio = await get_portfolio_instance()
        breakdown_data = await portfolio.get_holdings_breakdown()
        
        if "error" in breakdown_data:
            raise HTTPException(status_code=500, detail=breakdown_data["error"])
        
        # Backward compatibility: keep total_value as net_equity
        return {
            "total_value": breakdown_data.get("net_equity", 0),
            "gross_market_value": breakdown_data.get("gross_market_value", 0),
            "net_equity": breakdown_data.get("net_equity", 0),
            "margin_debit": breakdown_data.get("margin_debit", 0),
            "positions_count": breakdown_data.get("positions_count", 0),
            "largest_position_pct": breakdown_data.get("largest_position_pct", 0),
            "largest_position_symbol": breakdown_data.get("largest_position_symbol", ""),
            "concentration": breakdown_data.get("concentration", "N/A"),
            "position_sizes": breakdown_data.get("position_sizes", {}),
        }
    except Exception as e:
        logger.error(f"Error calculating holdings breakdown: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/health")
async def portfolio_health() -> Dict[str, str]:
    """Check portfolio service health and authentication"""
    try:
        portfolio = await get_portfolio_instance()

        if portfolio.authenticated:
            status = "connected"
        else:
            authenticated = await portfolio.authenticate()
            status = "connected" if authenticated else "disconnected"

        return {
            "status": status,
            "username": portfolio.username if portfolio.username else "not configured",
        }
    except Exception as e:
        logger.error(f"Error checking portfolio health: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


@portfolio_router.get("/connect-url")
async def get_connect_url(broker: Optional[str] = Query(None, description="Optional broker slug, e.g. ROBINHOOD")) -> Dict[str, str]:
    """
    Return a SnapTrade Connection Portal URL. Open this in a browser to
    link a brokerage account (Robinhood, Schwab, IBKR, Fidelity, …).
    The URL is short-lived (~5 min).
    """
    try:
        portfolio = await get_portfolio_instance()
        # Method only exists on SnapTradePortfolio
        url = await portfolio.get_connection_url(broker=broker)  # type: ignore[attr-defined]
        return {"redirect_uri": url}
    except AttributeError:
        raise HTTPException(status_code=501, detail="Connection portal not supported by current portfolio backend")
    except Exception as e:
        logger.error(f"Error generating connect URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@portfolio_router.get("/accounts")
async def get_accounts() -> List[Dict[str, Any]]:
    """Get list of connected accounts with their metadata"""
    try:
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_portfolio()
        
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])
        
        return data.get("accounts", [])
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Bulk portfolio scan — runs deep-dive over every ticker in SnapTrade portfolio
# ---------------------------------------------------------------------------

_SCAN_CACHE: Dict[Tuple[int, bool], Tuple[datetime, Dict[str, Any]]] = {}
_SCAN_TTL = timedelta(minutes=15)

# Common non-equity / crypto tickers to skip in bulk scan
_CRYPTO_SKIP = {
    "BTC", "ETH", "XRP", "DOGE", "LTC", "BCH", "SOL", "ADA", "AVAX",
    "MATIC", "DOT", "LINK", "UNI", "ATOM", "ETC", "XLM", "ALGO", "FIL",
    "AAVE", "SHIB", "PEPE", "BTCUSD", "ETHUSD",
}
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _eligible_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    s = symbol.upper()
    if s in _CRYPTO_SKIP:
        return False
    return bool(_TICKER_RE.match(s))


def _signals_summary(breakdown: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("technical", "projection", "narrative"):
        section = breakdown.get(key) or {}
        out[key] = {
            "score": section.get("score", 0),
            "reason": section.get("reason"),
        }
    return out


@portfolio_router.get("/scan")
async def scan_portfolio(
    top_n: int = Query(20, ge=1, le=100, description="Top N entries by composite score"),
    include_thesis: bool = Query(False, description="Run LLM thesis on top 5"),
    refresh: bool = Query(False, description="Bypass 15-minute cache"),
) -> Dict[str, Any]:
    """
    Bulk deep-dive scan across every equity ticker in the connected
    SnapTrade portfolio. Returns ranked summary plus optional thesis on
    the top 5 names.

    NOTE: On DigitalOcean App Platform this endpoint can hit the ~75s
    gateway timeout for larger portfolios. Prefer the background job
    pattern: POST /api/portfolio/scan then poll GET /api/portfolio/scan/{job_id}.
    """
    return await _execute_scan(top_n=top_n, include_thesis=include_thesis, refresh=refresh)


async def _execute_scan(top_n: int, include_thesis: bool, refresh: bool, progress_cb: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Internal coroutine that performs the full portfolio scan.

    Extracted so it can be reused by both the synchronous GET endpoint
    and the background job runner.
    """
    cache_key = (top_n, include_thesis)
    now = datetime.now()
    if not refresh:
        cached = _SCAN_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _SCAN_TTL:
            logger.info(f"Portfolio scan cache hit ({top_n=}, {include_thesis=})")
            return cached[1]

    try:
        portfolio = await get_portfolio_instance()
        positions = await portfolio.get_positions()
    except Exception as e:
        logger.error(f"Portfolio scan: failed to fetch positions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch portfolio: {e}")

    # Deduplicate by symbol — sum units and market values across accounts
    agg: Dict[str, Dict[str, float]] = {}
    skipped: List[str] = []
    for p in positions or []:
        sym = str(p.get("symbol") or "").upper().strip()
        if not _eligible_symbol(sym):
            if sym:
                skipped.append(sym)
            continue
        qty = float(p.get("quantity") or p.get("units") or 0)
        mv = float(p.get("market_value") or p.get("current_value") or 0)
        avg = float(p.get("average_buy_price") or p.get("avg_cost") or 0)
        cur = float(p.get("current_price") or 0)
        entry = agg.setdefault(
            sym, {"units": 0.0, "market_value": 0.0, "cost_basis": 0.0, "current_price": 0.0}
        )
        entry["units"] += qty
        entry["market_value"] += mv
        # Accumulate cost basis so a multi-account holding gets a units-weighted
        # average entry price (avg_cost = cost_basis / units). SnapTrade exposes
        # average_purchase_price per lot, NOT a true entry date.
        entry["cost_basis"] += qty * avg
        if cur:
            entry["current_price"] = cur

    if skipped:
        logger.info(f"Portfolio scan: skipped {len(skipped)} non-equity symbols: {sorted(set(skipped))}")

    portfolio_value = sum(v["market_value"] for v in agg.values())
    symbols = sorted(agg.keys())
    logger.info(f"Portfolio scan: running deep-dive over {len(symbols)} symbols")

    results: List[Dict[str, Any]] = []
    failed: List[Dict[str, str]] = []

    # Bounded concurrency: run deep-dives in parallel (3 at a time) to beat
    # DigitalOcean's ~500s gateway timeout that was killing the sequential loop.
    sem = asyncio.Semaphore(3)

    async def _scan_one(sym: str) -> Dict[str, Any]:
        async with sem:
            try:
                dd = await _run_deep_dive(sym, include_thesis=False, include_analytics=False)
                return {"symbol": sym, "_dd": dd}
            except Exception as e:  # noqa: BLE001
                return {"symbol": sym, "error": str(e)}

    total = len(symbols)
    if progress_cb:
        try:
            progress_cb(0, total)
        except Exception:
            pass

    tasks = [asyncio.create_task(_scan_one(s)) for s in symbols]
    gathered = []
    done_count = 0
    for fut in asyncio.as_completed(tasks):
        item = await fut
        gathered.append(item)
        done_count += 1
        if progress_cb:
            try:
                progress_cb(done_count, total)
            except Exception:
                pass

    # Build SPY completed-bar return series ONCE (per-process cached fetch) so
    # every per-ticker beta computation can reuse it without re-fetching.
    _spy_returns = None
    _spy_close = None
    if _scan_analytics is not None:
        try:
            _spy_df = _scan_analytics._completed(_scan_analytics._fetch_ohlcv(_scan_analytics._BENCHMARK))
            if _spy_df is not None:
                _spy_adj = _scan_analytics._adj_close(_spy_df)
                if _spy_adj is not None:
                    _spy_close = _spy_adj  # completed-bar SPY adj close (relative strength + regime)
                    _spy_returns = _scan_analytics._daily_returns(_spy_adj)
        except Exception as se:  # noqa: BLE001
            logger.warning(f"Failed to build SPY return series for analytics: {se}")

    for item in gathered:
        sym = item["symbol"]
        if "error" in item:
            logger.warning(f"Portfolio scan: deep-dive failed for {sym}: {item['error']}")
            failed.append({"symbol": sym, "error": item["error"]})
            continue
        dd = item["_dd"]
        mv = agg[sym]["market_value"]
        # Guard div-by-zero / NaN/inf: only divide when portfolio_value is a
        # finite, non-zero number. When portfolio_value is 0 (e.g. every
        # position was a skipped crypto/cash holding) every pct is 0.0.
        if portfolio_value and math.isfinite(portfolio_value):
            pct = mv / portfolio_value * 100
            if not math.isfinite(pct):
                pct = 0.0
        else:
            pct = 0.0
        units = agg[sym]["units"]
        cost_basis = agg[sym].get("cost_basis", 0.0)
        avg_cost = (cost_basis / units) if units else 0.0
        quote = dd.get("quote") or {}
        cur_price = quote.get("price") or agg[sym].get("current_price") or None
        entry = {
            "symbol": sym,
            "composite_score": dd.get("composite_score", 0),
            "verdict": dd.get("verdict", "N/A"),
            "scores": dd.get("scores", {}),
            "quote": dd.get("quote"),
            "projection": dd.get("projection", {}),
            "narrative": dd.get("narrative", {}),
            "signals_summary": _signals_summary(dd.get("breakdown", {}) or {}),
            "market_value": mv,
            "units": units,
            "avg_cost": avg_cost or None,
            "pct_of_portfolio": pct,
            "warnings": dd.get("warnings", []),
        }

        # Additive per-ticker analytics block (ATR stop/target, R-multiple,
        # distance-to-stop, position beta/vol, suggested 2.5%-risk size). Pure
        # functions live in backend/analytics/*; wiring/IO in scan_analytics.
        # Wrapped so any analytics failure degrades to absent, never a scan failure.
        if _scan_analytics is not None:
            try:
                an = _scan_analytics.per_ticker_analytics(
                    sym,
                    avg_cost=avg_cost or None,
                    current_price=cur_price,
                    account_value=portfolio_value or None,
                    entry_date=None,  # SnapTrade exposes no true entry date
                    spy_returns=_spy_returns,
                    spy_close=_spy_close,
                )
                if an:
                    entry["analytics"] = an
            except Exception as ae:  # noqa: BLE001
                logger.warning(f"Per-ticker analytics failed for {sym}: {ae}")

        results.append(entry)

    # Rank by composite score
    results.sort(key=lambda r: r.get("composite_score", 0) or 0, reverse=True)

    top_buys = [r for r in results if (r.get("composite_score") or 0) >= 6.0][:5]
    top_sells = sorted(
        [r for r in results if (r.get("composite_score") or 0) <= 4.0],
        key=lambda r: r.get("composite_score", 0) or 0,
    )[:5]
    # Middle band 4.0 < score < 6.0
    holds_band = [r for r in results if 4.0 < (r.get("composite_score") or 0) < 6.0]
    holds_band.sort(key=lambda r: r.get("market_value", 0) or 0, reverse=True)
    top_holds = holds_band[:5]

    # Optional LLM thesis on top 5
    if include_thesis and top_buys:
        for entry in top_buys[:5]:
            try:
                thesis_md, thesis_warnings = _generate_thesis(
                    entry["symbol"],
                    entry.get("quote"),
                    entry.get("scores", {}) or {},
                    {k: {"reason": v.get("reason")} for k, v in (entry.get("signals_summary", {}) or {}).items()},
                    entry.get("projection", {}) or {},
                    entry.get("narrative", {}) or {},
                    [],
                )
                entry["thesis_markdown"] = thesis_md
                entry["thesis_model"] = THESIS_MODEL
                if thesis_warnings:
                    entry.setdefault("warnings", []).extend(thesis_warnings)
            except Exception as e:
                logger.warning(f"Thesis generation failed for {entry['symbol']}: {e}")

    # Distinguish "empty portfolio" from "100% cash/crypto". portfolio_value
    # is the summed market value of *eligible* (scannable equity) holdings.
    # When it's 0 but we skipped symbols, the account isn't empty — it's
    # entirely cash / crypto / non-equity, which the UI should surface
    # differently from a genuinely empty account.
    skipped_unique = sorted(set(skipped))
    has_cash_or_skipped = portfolio_value == 0 and bool(skipped_unique)
    cash_pct = 100.0 if has_cash_or_skipped else 0.0
    if portfolio_value == 0:
        portfolio_state = "all_cash_or_crypto" if skipped_unique else "empty"
    else:
        portfolio_state = "has_equity"

    # Additive portfolio-level risk block: beta-to-SPY, annualized vol,
    # VaR (hist + parametric), synthetic max drawdown, Sharpe/Sortino,
    # ~1-month rolling correlation matrix, HHI + effective_number, sector
    # exposure. Degrades gracefully (per-ticker skips + data_gaps) and never
    # fails the scan. Sector data is "Unknown" (SnapTrade exposes no GICS sector).
    portfolio_risk_block = None
    if _scan_analytics is not None and results:
        try:
            holdings_for_risk = [
                {
                    "symbol": r["symbol"],
                    "market_value": r.get("market_value", 0.0),
                    "sector": None,  # SnapTrade has no sector; flagged in data_gaps
                }
                for r in results
            ]
            portfolio_risk_block = _scan_analytics.portfolio_risk(
                holdings_for_risk, portfolio_value
            )
        except Exception as pe:  # noqa: BLE001
            logger.warning(f"Portfolio risk analytics failed: {pe}")

    # Additive per-ticker sector-rotation tag: each holding's sector rotation
    # status (rotating-IN tailwind / rotating-OUT risk), joined from the daily
    # sector-rotation snapshot via map_to_companies. Computed ONCE for all
    # scanned symbols (one snapshot read, cached sector lookups) then attached
    # per entry. Fully wrapped — a tagging failure never breaks the scan.
    if _scan_analytics is not None and results:
        try:
            _rot_tags = _scan_analytics.sector_rotation_tags(
                [r["symbol"] for r in results]
            )
            if _rot_tags:
                for r in results:
                    tag = _rot_tags.get(r["symbol"])
                    if tag:
                        r["sector_rotation"] = tag
        except Exception as ge:  # noqa: BLE001
            logger.warning(f"Sector-rotation tagging failed: {ge}")

    # Additive payload-level market-regime block (label + size/stop bias),
    # read off the once-fetched SPY series. Fully wrapped: never fails the scan.
    regime_block = None
    if _scan_analytics is not None:
        try:
            regime_block = await _scan_analytics.regime_block(_spy_close)
        except Exception as re_:  # noqa: BLE001
            logger.warning(f"Regime analytics failed: {re_}")

    # Additive ranked multi-signal alerts: fuse each ticker's signals + insider +
    # risk + sector-rotation + regime into a weighted confluence score, ranked
    # into alert(>=80)/watch(60-79)/log(<60) buckets. Computed from the already-
    # assembled `results` (with their analytics + sector_rotation blocks) so no
    # extra fetching occurs. Fully wrapped — never fails the scan.
    alerts_block = None
    if _scan_analytics is not None and results:
        try:
            alerts_block = _scan_analytics.build_alerts(
                results, regime=regime_block, top_n=10
            )
        except Exception as ale:  # noqa: BLE001
            logger.warning(f"Alerts analytics failed: {ale}")

    payload = {
        "scanned_at": now.isoformat(),
        "tickers_scanned": len(results),
        "tickers_failed": len(failed),
        # Additive partial-failure surfacing: callers/UI can branch on this
        # without re-deriving it from the `failed` list.
        "partial_failure": bool(failed) and bool(results),
        "failed_count": len(failed),
        "portfolio_value": portfolio_value,
        # Cash/empty semantics so the UI can tell "empty account" apart from
        # "100% cash/crypto" — both yield portfolio_value == 0.
        "cash_pct": cash_pct,
        "portfolio_state": portfolio_state,
        "skipped_symbols": skipped_unique,
        "top_buys": top_buys,
        "top_sells": top_sells,
        "top_holds": top_holds,
        "ranked": results[:top_n],
        "failed": failed,
    }

    # Additive, non-breaking: only attach when computed.
    if portfolio_risk_block is not None:
        payload["portfolio_risk"] = portfolio_risk_block
    if regime_block is not None:
        payload["regime"] = regime_block
    if alerts_block:
        payload["alerts"] = alerts_block

    _SCAN_CACHE[cache_key] = (now, payload)
    return payload


# ---------------------------------------------------------------------------
# Background job pattern — bypass DigitalOcean App Platform's ~75s gateway
# timeout. Clients POST to /scan to enqueue, then poll GET /scan/{job_id}.
# ---------------------------------------------------------------------------

_scan_jobs: Dict[str, Dict[str, Any]] = {}
_JOB_TTL = 30 * 60  # 30 minutes
_jobs_lock = asyncio.Lock()


def _gc_jobs() -> None:
    """Drop jobs older than _JOB_TTL seconds."""
    now = time.time()
    expired = [jid for jid, j in _scan_jobs.items() if now - j["created_at"] > _JOB_TTL]
    for jid in expired:
        _scan_jobs.pop(jid, None)


# ---------------------------------------------------------------------------
# Daily-snapshot cache — persist the latest completed scan to disk so the
# dashboard can render instantly without kicking off a fresh 3-min scan.
# ---------------------------------------------------------------------------

def _snapshot_path() -> str:
    return os.environ.get("SCAN_SNAPSHOT_PATH", "/tmp/portfolio_scan_latest.json")


# Redis-backed snapshot — durable across DO container restarts/deploys (the /tmp
# disk snapshot is ephemeral and wiped every deploy, so the page kept finding no
# cache and re-scanning). Instantiate with the REAL REDIS_URL, not CacheManager's
# localhost default (which would silently fall back to per-instance in-memory).
from cache_manager import CacheManager  # noqa: E402

_snapshot_cache = CacheManager(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
_SNAPSHOT_REDIS_KEY = "portfolio:scan:latest"
_SNAPSHOT_REDIS_TTL = 7 * 24 * 3600  # refreshed by every scan + the nightly cron


def _save_scan_snapshot(result: Dict[str, Any]) -> Optional[str]:
    """Atomically write the latest completed scan result + metadata to disk.

    Returns the snapshot path on success, None on failure. Failures are logged
    but never raised — caching is best-effort and must not break a scan job.
    """
    try:
        path = _snapshot_path()
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        now_utc = datetime.now(timezone.utc)
        try:
            now_pt = now_utc.astimezone(_PT_TZ)
        except Exception:
            now_pt = now_utc
        payload = {
            "saved_at": now_utc.isoformat(),
            "saved_at_pt": now_pt.isoformat(),
            "result": result,
        }
        fd, tmp = tempfile.mkstemp(
            prefix=".portfolio_scan_latest.", suffix=".json", dir=parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, default=str)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # Durable copy in Redis (survives DO restarts/deploys; /tmp does not).
        try:
            rc = getattr(_snapshot_cache, "redis_client", None)
            if rc is not None:
                rc.setex(
                    _SNAPSHOT_REDIS_KEY,
                    _SNAPSHOT_REDIS_TTL,
                    json.dumps(payload, default=str),
                )
        except Exception as _re:  # noqa: BLE001
            logger.warning(f"Failed to write scan snapshot to Redis: {_re}")
        logger.info(f"Portfolio scan snapshot written to {path}")
        return path
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to write scan snapshot: {e}")
        return None


async def _run_scan_job(job_id: str, top_n: int, include_thesis: bool, refresh: bool) -> None:
    """Background runner — drives _execute_scan and updates the job record."""
    _gc_jobs()
    job = _scan_jobs.get(job_id)
    if not job:
        return
    job["status"] = "running"
    job["started_at"] = time.time()
    try:
        def _cb(scanned: int, total: int) -> None:
            pct = int((scanned / total) * 100) if total else 0
            job["progress"] = {"scanned": scanned, "total": total, "percent": pct}

        result = await _execute_scan(top_n=top_n, include_thesis=include_thesis, refresh=refresh, progress_cb=_cb)
        job["result"] = result
        job["status"] = "complete"
        job["completed_at"] = time.time()
        scanned = result.get("scanned", result.get("tickers_scanned", 0))
        total = job.get("progress", {}).get("total") or scanned
        job["progress"] = {"scanned": scanned, "total": total, "percent": 100}
        # Best-effort: persist latest completed scan so the dashboard can load
        # instantly from disk instead of waiting on a fresh 3-min scan.
        try:
            _save_scan_snapshot(result)
        except Exception as snap_err:  # noqa: BLE001
            logger.warning(f"Snapshot persist failed (non-fatal): {snap_err}")
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
        job["completed_at"] = time.time()


@portfolio_router.post("/scan", status_code=202)
async def start_scan_job(
    top_n: int = Query(10, ge=1, le=100),
    include_thesis: bool = Query(False),
    refresh: bool = Query(False),
) -> Dict[str, Any]:
    """Enqueue a portfolio scan and return a job_id immediately (HTTP 202).

    Poll GET /api/portfolio/scan/{job_id} for status + results.
    """
    _gc_jobs()
    job_id = str(uuid.uuid4())
    _scan_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": time.time(),
        "params": {"top_n": top_n, "include_thesis": include_thesis, "refresh": refresh},
        "result": None,
        "error": None,
        "progress": {"scanned": 0, "total": 0},
    }
    asyncio.create_task(_run_scan_job(job_id, top_n, include_thesis, refresh))
    return {"job_id": job_id, "status": "queued", "message": "Scan started"}


@portfolio_router.get("/scan/latest")
async def get_scan_latest():
    """Return the most recently persisted completed scan snapshot.

    The snapshot is written to disk by the background job runner whenever
    a scan finishes successfully (including the nightly cron run). The
    dashboard hits this endpoint on mount so it can render instantly
    instead of triggering a fresh 3-minute scan every visit.
    """
    # Prefer the durable Redis copy; fall back to the ephemeral disk snapshot.
    data = None
    try:
        rc = getattr(_snapshot_cache, "redis_client", None)
        if rc is not None:
            raw = rc.get(_SNAPSHOT_REDIS_KEY)
            if raw:
                data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Redis snapshot read failed: {e}")

    if data is None:
        path = _snapshot_path()
        if not os.path.exists(path):
            return JSONResponse(status_code=404, content={"error": "no snapshot available yet"})
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read scan snapshot {path}: {e}")
            return JSONResponse(status_code=500, content={"error": f"snapshot read failed: {e}"})

    saved_at = data.get("saved_at")
    age_minutes = 0
    if saved_at:
        try:
            dt = datetime.fromisoformat(saved_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            age_minutes = int(delta.total_seconds() // 60)
        except Exception:
            age_minutes = 0

    return {
        "saved_at": data.get("saved_at"),
        "saved_at_pt": data.get("saved_at_pt"),
        "result": data.get("result"),
        "age_minutes": age_minutes,
    }


@portfolio_router.get("/scan/{job_id}")
async def get_scan_job(job_id: str) -> Dict[str, Any]:
    """Return the current status (and result, if complete) of a scan job."""
    _gc_jobs()
    job = _scan_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Scan job {job_id} not found")
    return job
