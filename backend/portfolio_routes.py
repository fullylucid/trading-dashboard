"""
Portfolio API Routes
FastAPI endpoints for brokerage portfolio tracking and display.

Backed by SnapTrade (OAuth) — see snaptrade_portfolio.py. The legacy
robinhood_portfolio.py remains in the tree as a fallback but is no
longer wired up.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime

from snaptrade_portfolio import get_portfolio_instance, clear_portfolio_cache

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
        
        return {
            "total_value": data.get("account_value", 0),
            "buying_power": data.get("buying_power", 0),
            "cash": data.get("cash", 0),
            "positions_count": summary.get("total_positions", 0),
            "total_gain_loss": summary.get("total_gain_loss", 0),
            "total_gain_loss_pct": summary.get("total_gain_loss_pct", 0),
            "top_position": summary.get("top_position"),
            "timestamp": data.get("timestamp"),
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
        data = await portfolio.get_portfolio()
        
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])
        
        positions = data.get("positions", [])
        
        if not positions:
            return {
                "total_value": 0,
                "positions_count": 0,
                "largest_position_pct": 0,
                "concentration": "N/A",
            }
        
        total_value = sum(p["current_value"] for p in positions)
        largest_position = max(p["current_value"] for p in positions) if positions else 0
        largest_position_pct = (largest_position / total_value * 100) if total_value > 0 else 0
        
        # Determine concentration level
        if largest_position_pct > 50:
            concentration = "HIGHLY CONCENTRATED"
        elif largest_position_pct > 30:
            concentration = "CONCENTRATED"
        elif largest_position_pct > 20:
            concentration = "MODERATE"
        else:
            concentration = "DIVERSIFIED"
        
        # Calculate position sizes
        position_sizes = {}
        for pos in positions:
            pct = (pos["current_value"] / total_value * 100) if total_value > 0 else 0
            if pct >= 10:
                size_category = "LARGE (>10%)"
            elif pct >= 5:
                size_category = "MEDIUM (5-10%)"
            else:
                size_category = "SMALL (<5%)"
            
            if size_category not in position_sizes:
                position_sizes[size_category] = 0
            position_sizes[size_category] += 1
        
        return {
            "total_value": total_value,
            "positions_count": len(positions),
            "largest_position_pct": round(largest_position_pct, 2),
            "largest_position_symbol": positions[0]["symbol"],
            "concentration": concentration,
            "position_sizes": position_sizes,
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
