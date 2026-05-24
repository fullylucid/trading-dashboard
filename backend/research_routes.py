"""
Research Routes — FastAPI routers for news, earnings, market data, and research.

Exposes four module-level routers (so main.py can include_router each at module
import time) plus an initialize_services(...) function the app calls during
startup to inject service instances.

Routers (paths match the frontend client in src/services/):
- news_router      mounted at /api/news        — symbol/market/sector news
- earnings_router  mounted at /api/earnings    — calendar, surprises, per-symbol
- market_router    mounted at /api/market      — overview, sectors, breadth, summary
- research_router  mounted at /api/research    — analyze/{symbol}, summarize, etc.
"""

from datetime import datetime
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service registry — injected at startup via initialize_services()
# ---------------------------------------------------------------------------

_services: dict = {
    "news_agg": None,
    "earnings_cal": None,
    "market_data": None,
    "research_agent": None,
}


def initialize_services(
    news_agg=None,
    earnings_cal=None,
    market_data=None,
    research_agent=None,
) -> None:
    """Wire service instances into the route handlers.

    Called once from main.py's lifespan/startup. Handlers read from the
    `_services` dict so they always see the current instances even if
    initialize_services is called more than once.
    """
    _services["news_agg"] = news_agg
    _services["earnings_cal"] = earnings_cal
    _services["market_data"] = market_data
    _services["research_agent"] = research_agent
    logger.info(
        "research_routes services initialized: "
        "news=%s earnings=%s market=%s research=%s",
        bool(news_agg), bool(earnings_cal), bool(market_data), bool(research_agent),
    )


def _need(name: str):
    """Return a service or raise 503 if it wasn't initialized."""
    svc = _services.get(name)
    if svc is None:
        raise HTTPException(status_code=503, detail=f"{name} not initialized")
    return svc


# ---------------------------------------------------------------------------
# News router — /api/news
# ---------------------------------------------------------------------------

news_router = APIRouter(prefix="/api/news", tags=["news"])


@news_router.get("/market")
async def get_market_news(limit: int = Query(30, le=100)):
    """General market news."""
    try:
        news_agg = _need("news_agg")
        news = await news_agg.fetch_market_news(limit=limit)
        return {
            "news_type": "market_news",
            "article_count": len(news),
            "articles": news,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Market news fetch error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@news_router.get("/sector/{sector}")
async def get_sector_news(sector: str, limit: int = Query(15, le=50)):
    """News scoped to a sector."""
    try:
        news_agg = _need("news_agg")
        news = await news_agg.fetch_sector_news(sector=sector, limit=limit)
        return {
            "sector": sector,
            "article_count": len(news),
            "articles": news,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sector news fetch error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# Frontend uses both /api/news/symbol/AAPL and /api/news/AAPL — support both.
@news_router.get("/symbol/{symbol}")
@news_router.get("/{symbol}")
async def get_symbol_news(
    symbol: str,
    limit: int = Query(20, le=100),
    days: int = Query(30, le=365),
):
    """News for a specific symbol."""
    try:
        news_agg = _need("news_agg")
        news = await news_agg.fetch_symbol_news(symbol.upper(), limit=limit)
        return {
            "symbol": symbol.upper(),
            "news_count": len(news),
            "articles": news,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("News fetch error for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


@news_router.get("/category/{category}")
async def get_category_news(category: str, limit: int = Query(20, le=100)):
    """News by category — falls back to market news if aggregator lacks the method."""
    try:
        news_agg = _need("news_agg")
        if hasattr(news_agg, "fetch_category_news"):
            news = await news_agg.fetch_category_news(category=category, limit=limit)
        else:
            news = await news_agg.fetch_market_news(limit=limit)
        return {
            "category": category,
            "article_count": len(news),
            "articles": news,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Category news fetch error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Earnings router — /api/earnings
# ---------------------------------------------------------------------------

earnings_router = APIRouter(prefix="/api/earnings", tags=["earnings"])


@earnings_router.get("/calendar")
@earnings_router.get("/upcoming")
async def get_earnings_calendar(
    days: int = Query(90, le=365),
    limit: int = Query(100, le=500),
):
    """Upcoming earnings calendar."""
    try:
        earnings_cal = _need("earnings_cal")
        earnings = await earnings_cal.fetch_upcoming_earnings(days=days, limit=limit)
        return {
            "earnings_count": len(earnings),
            "days_ahead": days,
            "earnings": earnings,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Earnings calendar error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@earnings_router.get("/surprises")
async def get_earnings_surprises(days: int = Query(30, le=90)):
    """Recent earnings surprises + season stats."""
    try:
        earnings_cal = _need("earnings_cal")
        surprises = await earnings_cal.fetch_earnings_surprises(days=days)
        season_stats = earnings_cal.calculate_earnings_season(surprises)
        return {
            "surprise_count": len(surprises),
            "surprises": surprises,
            "season_stats": season_stats,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Earnings surprises error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@earnings_router.get("/history/{symbol}")
async def get_symbol_earnings_history(symbol: str, limit: int = Query(8, le=40)):
    """Historical earnings for a symbol (best-effort — falls back to upcoming filter)."""
    try:
        earnings_cal = _need("earnings_cal")
        if hasattr(earnings_cal, "fetch_earnings_history"):
            history = await earnings_cal.fetch_earnings_history(symbol.upper(), limit=limit)
        else:
            all_earnings = await earnings_cal.fetch_upcoming_earnings(limit=500)
            history = [e for e in all_earnings if e.get("symbol") == symbol.upper()]
        return {
            "symbol": symbol.upper(),
            "history_count": len(history),
            "history": history,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Earnings history error for %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


@earnings_router.get("/{symbol}")
async def get_symbol_earnings(symbol: str):
    """Next upcoming earnings event for a symbol."""
    try:
        earnings_cal = _need("earnings_cal")
        all_earnings = await earnings_cal.fetch_upcoming_earnings(limit=100)
        symbol_earnings = [e for e in all_earnings if e.get("symbol") == symbol.upper()]
        if not symbol_earnings:
            return {
                "symbol": symbol.upper(),
                "next_earnings": None,
                "message": "No upcoming earnings found",
            }
        return {
            "symbol": symbol.upper(),
            "next_earnings": symbol_earnings[0],
            "upcoming": symbol_earnings,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Symbol earnings error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Market router — /api/market
# ---------------------------------------------------------------------------

market_router = APIRouter(prefix="/api/market", tags=["market"])


@market_router.get("/overview")
async def get_market_overview():
    """Indices + headline figures."""
    try:
        market_data = _need("market_data")
        overview = await market_data.fetch_market_overview()
        return {"indices": overview, "timestamp": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Market overview error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@market_router.get("/sectors")
async def get_sector_performance():
    """Sector performance rankings."""
    try:
        market_data = _need("market_data")
        return await market_data.fetch_sector_performance()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sector performance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@market_router.get("/breadth")
async def get_market_breadth():
    """Advancers/decliners/new highs etc."""
    try:
        market_data = _need("market_data")
        return await market_data.fetch_market_breadth()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Market breadth error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@market_router.get("/summary")
async def get_market_summary():
    """Composite market summary."""
    try:
        market_data = _need("market_data")
        return await market_data.get_market_summary()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Market summary error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@market_router.get("/vix")
async def get_vix():
    """VIX — falls back gracefully if not implemented."""
    try:
        market_data = _need("market_data")
        if hasattr(market_data, "fetch_vix"):
            return await market_data.fetch_vix()
        # Fall back: pull from overview if VIX is present
        overview = await market_data.fetch_market_overview()
        return {"vix": overview.get("VIX") if isinstance(overview, dict) else None,
                "timestamp": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("VIX error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@market_router.get("/treasuries")
async def get_treasuries():
    """Treasury yields — falls back gracefully."""
    try:
        market_data = _need("market_data")
        if hasattr(market_data, "fetch_treasuries"):
            return await market_data.fetch_treasuries()
        return {"treasuries": [], "timestamp": datetime.now().isoformat(),
                "note": "treasuries endpoint not implemented on market_data"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Treasuries error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@market_router.get("/commodities")
async def get_commodities():
    """Commodity prices — falls back gracefully."""
    try:
        market_data = _need("market_data")
        if hasattr(market_data, "fetch_commodities"):
            return await market_data.fetch_commodities()
        return {"commodities": [], "timestamp": datetime.now().isoformat(),
                "note": "commodities endpoint not implemented on market_data"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Commodities error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Research router — /api/research
# ---------------------------------------------------------------------------

research_router = APIRouter(prefix="/api/research", tags=["research"])


@research_router.post("/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    research_type: str = Query(
        "comprehensive", regex="^(comprehensive|earnings|sec|alpha)$"
    ),
):
    """Run a research agent against a symbol."""
    try:
        research_agent = _need("research_agent")
        news_agg = _services.get("news_agg")
        earnings_cal = _services.get("earnings_cal")

        news = []
        if news_agg:
            news = await news_agg.fetch_symbol_news(symbol.upper(), limit=3)

        earnings = None
        if earnings_cal:
            all_earnings = await earnings_cal.fetch_upcoming_earnings(limit=100)
            earnings = next(
                (e for e in all_earnings if e.get("symbol") == symbol.upper()), None
            )

        context = {
            "symbol": symbol.upper(),
            "recent_news": news,
            "upcoming_earnings": earnings,
        }

        result = {
            "symbol": symbol.upper(),
            "research_type": research_type,
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
        }

        if research_type == "comprehensive":
            result["analysis"] = "Comprehensive research analysis pending..."
        elif research_type == "earnings":
            if earnings:
                analysis = await research_agent.summarize_earnings_report(
                    symbol.upper(),
                    "Report data would go here",
                    context.get("company_name", ""),
                )
                result["earnings_analysis"] = analysis
            else:
                result["message"] = "No upcoming earnings found"
        elif research_type == "alpha":
            analysis = await research_agent.identify_alpha_signals(symbol.upper(), context)
            result["alpha_signals"] = analysis

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Research analysis error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@research_router.post("/summarize")
async def summarize(payload: dict):
    """Summarize an arbitrary text blob (best-effort)."""
    try:
        research_agent = _need("research_agent")
        text = payload.get("text", "")
        if not text:
            raise HTTPException(status_code=400, detail="missing 'text'")
        if hasattr(research_agent, "summarize"):
            summary = await research_agent.summarize(text)
        else:
            summary = text[:500]
        return {"summary": summary, "timestamp": datetime.now().isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Summarize error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@research_router.get("/sentiment/{symbol}")
@research_router.get("/sentiment")
async def get_sentiment(symbol: Optional[str] = None):
    """Sentiment score for a symbol — falls back gracefully."""
    try:
        research_agent = _need("research_agent")
        if hasattr(research_agent, "fetch_sentiment") and symbol:
            return await research_agent.fetch_sentiment(symbol.upper())
        return {
            "symbol": symbol.upper() if symbol else None,
            "sentiment": None,
            "note": "sentiment endpoint not implemented on research_agent",
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sentiment error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# Aliases the frontend hits through /api/research/* — proxy to the canonical handlers.

@research_router.get("/news/{symbol}")
async def research_news_alias(symbol: str, limit: int = Query(20, le=100)):
    return await get_symbol_news(symbol=symbol, limit=limit, days=30)


@research_router.get("/earnings/calendar")
async def research_earnings_calendar_alias(
    days: int = Query(90, le=365), limit: int = Query(100, le=500)
):
    return await get_earnings_calendar(days=days, limit=limit)


@research_router.get("/earnings/{symbol}")
async def research_earnings_alias(symbol: str):
    return await get_symbol_earnings(symbol=symbol)


@research_router.get("/market/overview")
async def research_market_overview_alias():
    return await get_market_overview()


@research_router.get("/market/sectors")
async def research_market_sectors_alias():
    return await get_sector_performance()
