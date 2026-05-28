"""
Portfolio API Routes
FastAPI endpoints for brokerage portfolio tracking and display.

Backed by SnapTrade (OAuth) — see snaptrade_portfolio.py. The legacy
robinhood_portfolio.py remains in the tree as a fallback but is no
longer wired up.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List, Dict, Any, Tuple
import asyncio
import logging
import re
from datetime import datetime, timedelta

from snaptrade_portfolio import get_portfolio_instance, clear_portfolio_cache
from deep_dive_routes import _run_deep_dive, _generate_thesis, THESIS_MODEL

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
        entry = agg.setdefault(sym, {"units": 0.0, "market_value": 0.0})
        entry["units"] += qty
        entry["market_value"] += mv

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
                dd = await _run_deep_dive(sym, include_thesis=False)
                return {"symbol": sym, "_dd": dd}
            except Exception as e:  # noqa: BLE001
                return {"symbol": sym, "error": str(e)}

    gathered = await asyncio.gather(*[_scan_one(s) for s in symbols])

    for item in gathered:
        sym = item["symbol"]
        if "error" in item:
            logger.warning(f"Portfolio scan: deep-dive failed for {sym}: {item['error']}")
            failed.append({"symbol": sym, "error": item["error"]})
            continue
        dd = item["_dd"]
        mv = agg[sym]["market_value"]
        pct = (mv / portfolio_value * 100) if portfolio_value else 0.0
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
            "units": agg[sym]["units"],
            "pct_of_portfolio": pct,
            "warnings": dd.get("warnings", []),
        }
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

    payload = {
        "scanned_at": now.isoformat(),
        "tickers_scanned": len(results),
        "tickers_failed": len(failed),
        "portfolio_value": portfolio_value,
        "skipped_symbols": sorted(set(skipped)),
        "top_buys": top_buys,
        "top_sells": top_sells,
        "top_holds": top_holds,
        "ranked": results[:top_n],
        "failed": failed,
    }

    _SCAN_CACHE[cache_key] = (now, payload)
    return payload
