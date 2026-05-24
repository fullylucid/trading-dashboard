"""
Research Routes - FastAPI endpoints for research data, news, earnings, and market data

Endpoints:
- GET /api/news/{symbol} - News for specific symbol
- GET /api/news/market - General market news
- GET /api/earnings/calendar - Upcoming earnings
- GET /api/earnings/surprises - Recent earnings surprises
- GET /api/market/overview - Market summary
- GET /api/market/sectors - Sector performance
- POST /api/research/analyze - Research analysis for symbol
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# These will be imported from the actual modules
# from news_aggregator import get_news_aggregator
# from earnings_calendar import get_earnings_calendar
# from market_data import get_market_data
# from research_agent import get_research_agent

def create_research_routes(
    news_agg=None,
    earnings_cal=None,
    market_data=None,
    research_agent=None
) -> APIRouter:
    """
    Create research routes router
    
    Args:
        news_agg: NewsAggregator instance
        earnings_cal: EarningsCalendar instance
        market_data: MarketData instance
        research_agent: ResearchAgent instance
    
    Returns:
        APIRouter with all research endpoints
    """
    router = APIRouter(prefix="/api/research", tags=["research"])
    
    # NEWS ENDPOINTS
    
    @router.get("/news/{symbol}")
    async def get_symbol_news(
        symbol: str,
        limit: int = Query(20, le=100),
        days: int = Query(30, le=365)
    ):
        """Get news for specific symbol"""
        try:
            if not news_agg:
                return {"error": "News aggregator not initialized"}
            
            news = await news_agg.fetch_symbol_news(symbol.upper(), limit=limit)
            
            return {
                "symbol": symbol.upper(),
                "news_count": len(news),
                "articles": news,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"News fetch error for {symbol}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/news/market")
    async def get_market_news(limit: int = Query(30, le=100)):
        """Get general market news"""
        try:
            if not news_agg:
                return {"error": "News aggregator not initialized"}
            
            news = await news_agg.fetch_market_news(limit=limit)
            
            return {
                "news_type": "market_news",
                "article_count": len(news),
                "articles": news,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Market news fetch error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/news/sector/{sector}")
    async def get_sector_news(
        sector: str,
        limit: int = Query(15, le=50)
    ):
        """Get news for specific sector"""
        try:
            if not news_agg:
                return {"error": "News aggregator not initialized"}
            
            news = await news_agg.fetch_sector_news(sector=sector, limit=limit)
            
            return {
                "sector": sector,
                "article_count": len(news),
                "articles": news,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Sector news fetch error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # EARNINGS ENDPOINTS
    
    @router.get("/earnings/calendar")
    async def get_earnings_calendar(
        days: int = Query(90, le=365),
        limit: int = Query(100, le=500)
    ):
        """Get upcoming earnings calendar"""
        try:
            if not earnings_cal:
                return {"error": "Earnings calendar not initialized"}
            
            earnings = await earnings_cal.fetch_upcoming_earnings(days=days, limit=limit)
            
            return {
                "earnings_count": len(earnings),
                "days_ahead": days,
                "earnings": earnings,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Earnings calendar error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/earnings/surprises")
    async def get_earnings_surprises(
        days: int = Query(30, le=90)
    ):
        """Get recent earnings surprises"""
        try:
            if not earnings_cal:
                return {"error": "Earnings calendar not initialized"}
            
            surprises = await earnings_cal.fetch_earnings_surprises(days=days)
            
            # Get season stats
            season_stats = earnings_cal.calculate_earnings_season(surprises)
            
            return {
                "surprise_count": len(surprises),
                "surprises": surprises,
                "season_stats": season_stats,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Earnings surprises error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/earnings/{symbol}")
    async def get_symbol_earnings(symbol: str):
        """Get upcoming earnings for specific symbol"""
        try:
            if not earnings_cal:
                return {"error": "Earnings calendar not initialized"}
            
            all_earnings = await earnings_cal.fetch_upcoming_earnings(limit=100)
            
            # Filter for symbol
            symbol_earnings = [e for e in all_earnings if e["symbol"] == symbol.upper()]
            
            if not symbol_earnings:
                return {
                    "symbol": symbol.upper(),
                    "next_earnings": None,
                    "message": "No upcoming earnings found"
                }
            
            return {
                "symbol": symbol.upper(),
                "next_earnings": symbol_earnings[0] if symbol_earnings else None,
                "upcoming": symbol_earnings,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Symbol earnings error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # MARKET DATA ENDPOINTS
    
    @router.get("/market/overview")
    async def get_market_overview():
        """Get market overview and indices"""
        try:
            if not market_data:
                return {"error": "Market data not initialized"}
            
            overview = await market_data.fetch_market_overview()
            
            return {
                "indices": overview,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Market overview error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/market/sectors")
    async def get_sector_performance():
        """Get sector performance rankings"""
        try:
            if not market_data:
                return {"error": "Market data not initialized"}
            
            sectors = await market_data.fetch_sector_performance()
            
            return sectors
        except Exception as e:
            logger.error(f"Sector performance error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/market/breadth")
    async def get_market_breadth():
        """Get market breadth data"""
        try:
            if not market_data:
                return {"error": "Market data not initialized"}
            
            breadth = await market_data.fetch_market_breadth()
            
            return breadth
        except Exception as e:
            logger.error(f"Market breadth error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/market/summary")
    async def get_market_summary():
        """Get complete market summary"""
        try:
            if not market_data:
                return {"error": "Market data not initialized"}
            
            summary = await market_data.get_market_summary()
            
            return summary
        except Exception as e:
            logger.error(f"Market summary error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # RESEARCH ANALYSIS ENDPOINTS
    
    @router.post("/analyze/{symbol}")
    async def analyze_symbol(
        symbol: str,
        research_type: str = Query("comprehensive", regex="^(comprehensive|earnings|sec|alpha)$")
    ):
        """
        Analyze symbol using Kimi K research agent
        
        Types:
        - comprehensive: Full research analysis
        - earnings: Focus on earnings reports
        - sec: SEC filing analysis
        - alpha: Alpha signal identification
        """
        try:
            if not research_agent:
                return {
                    "error": "Research agent not initialized",
                    "symbol": symbol,
                    "status": "unavailable"
                }
            
            # Get news context
            news = []
            if news_agg:
                news = await news_agg.fetch_symbol_news(symbol.upper(), limit=3)
            
            # Get earnings context
            earnings = None
            if earnings_cal:
                all_earnings = await earnings_cal.fetch_upcoming_earnings(limit=100)
                earnings = next((e for e in all_earnings if e["symbol"] == symbol.upper()), None)
            
            context = {
                "symbol": symbol.upper(),
                "recent_news": news,
                "upcoming_earnings": earnings
            }
            
            # Perform research based on type
            result = {
                "symbol": symbol.upper(),
                "research_type": research_type,
                "timestamp": datetime.now().isoformat(),
                "status": "completed"
            }
            
            if research_type == "comprehensive":
                # Full analysis would go here
                result["analysis"] = "Comprehensive research analysis pending..."
            elif research_type == "earnings":
                if earnings:
                    analysis = await research_agent.summarize_earnings_report(
                        symbol.upper(),
                        "Report data would go here",
                        context.get("company_name", "")
                    )
                    result["earnings_analysis"] = analysis
                else:
                    result["message"] = "No upcoming earnings found"
            elif research_type == "alpha":
                analysis = await research_agent.identify_alpha_signals(
                    symbol.upper(),
                    context
                )
                result["alpha_signals"] = analysis
            
            return result
        
        except Exception as e:
            logger.error(f"Research analysis error: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
