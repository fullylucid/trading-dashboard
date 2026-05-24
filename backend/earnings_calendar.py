"""
Earnings Calendar - Tracks upcoming earnings with estimates vs actuals
Uses FMP (Financial Modeling Prep) and other APIs
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

class EarningsCalendar:
    """Manages earnings calendar and earnings surprises"""
    
    def __init__(self, fmp_key: str = ""):
        self.fmp_key = fmp_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(hours=2)  # 2 hour cache for earnings data
    
    async def initialize(self):
        """Initialize async session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    async def fetch_upcoming_earnings(self, days: int = 90, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch upcoming earnings for next N days
        
        Returns: List of earnings with symbol, date, estimates, sector
        """
        cache_key = f"earnings_{days}d"
        
        if cache_key in self.cache:
            if datetime.now() - self.cache_time.get(cache_key, datetime.now()) < self.cache_ttl:
                return self.cache[cache_key]
        
        await self.initialize()
        earnings = []
        
        try:
            if self.fmp_key:
                # FMP earnings calendar
                async with self.session.get(
                    "https://financialmodelingprep.com/api/v3/earnings-calendar",
                    params={
                        "apikey": self.fmp_key,
                        "limit": limit
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Filter for upcoming earnings within next N days
                        cutoff_date = (datetime.now() + timedelta(days=days)).date()
                        
                        for item in data:
                            try:
                                earnings_date = datetime.strptime(item.get("date", ""), "%Y-%m-%d").date()
                                
                                if datetime.now().date() <= earnings_date <= cutoff_date:
                                    earnings.append({
                                        "symbol": item.get("symbol", ""),
                                        "company_name": item.get("company", ""),
                                        "sector": item.get("sector", ""),
                                        "date": item.get("date", ""),
                                        "time": item.get("time", ""),
                                        "eps_estimate": float(item.get("epsEstimated", 0) or 0),
                                        "eps_actual": float(item.get("eps", 0) or 0) if item.get("eps") else None,
                                        "revenue_estimate": float(item.get("revenueEstimated", 0) or 0),
                                        "revenue_actual": float(item.get("revenue", 0) or 0) if item.get("revenue") else None,
                                        "market_cap": item.get("marketCap", ""),
                                        "price": float(item.get("price", 0) or 0),
                                        "change_percent": float(item.get("change", 0) or 0)
                                    })
                            except (ValueError, TypeError) as e:
                                logger.warning(f"Error parsing earnings item: {str(e)}")
                                continue
                        
                        # Sort by date
                        earnings.sort(key=lambda x: x["date"])
                        earnings = earnings[:limit]
        
        except Exception as e:
            logger.error(f"Earnings calendar fetch error: {str(e)}")
        
        # Cache results
        self.cache[cache_key] = earnings
        self.cache_time[cache_key] = datetime.now()
        
        return earnings
    
    async def fetch_earnings_surprises(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Fetch recent earnings with actual vs estimate
        Identifies surprises
        """
        cache_key = "earnings_surprises"
        
        if cache_key in self.cache:
            if datetime.now() - self.cache_time.get(cache_key, datetime.now()) < self.cache_ttl:
                return self.cache[cache_key]
        
        await self.initialize()
        surprises = []
        
        try:
            if self.fmp_key:
                # Get past earnings with actuals
                async with self.session.get(
                    "https://financialmodelingprep.com/api/v3/earnings-calendar",
                    params={
                        "apikey": self.fmp_key,
                        "limit": 200
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        cutoff_date = (datetime.now() - timedelta(days=days)).date()
                        
                        for item in data:
                            try:
                                if item.get("eps") and item.get("epsEstimated"):
                                    earnings_date = datetime.strptime(item.get("date", ""), "%Y-%m-%d").date()
                                    
                                    if cutoff_date <= earnings_date <= datetime.now().date():
                                        eps_actual = float(item.get("eps"))
                                        eps_estimate = float(item.get("epsEstimated", 0) or 0)
                                        
                                        if eps_estimate > 0:
                                            surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100
                                        else:
                                            surprise_pct = 0
                                        
                                        surprises.append({
                                            "symbol": item.get("symbol", ""),
                                            "company_name": item.get("company", ""),
                                            "date": item.get("date", ""),
                                            "eps_estimate": eps_estimate,
                                            "eps_actual": eps_actual,
                                            "surprise_pct": surprise_pct,
                                            "beat": eps_actual > eps_estimate,
                                            "revenue_estimate": float(item.get("revenueEstimated", 0) or 0),
                                            "revenue_actual": float(item.get("revenue", 0) or 0),
                                            "price_change": float(item.get("change", 0) or 0),
                                            "sector": item.get("sector", "")
                                        })
                            except (ValueError, TypeError):
                                continue
                        
                        # Sort by surprise size (largest first)
                        surprises.sort(key=lambda x: abs(x["surprise_pct"]), reverse=True)
        
        except Exception as e:
            logger.error(f"Earnings surprises fetch error: {str(e)}")
        
        self.cache[cache_key] = surprises
        self.cache_time[cache_key] = datetime.now()
        
        return surprises
    
    def calculate_earnings_season(self, earnings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze earnings season patterns
        
        Returns: Summary statistics about current earnings season
        """
        if not earnings:
            return {
                "total_earnings": 0,
                "by_sector": {},
                "beat_rate": 0,
                "surprise_avg": 0
            }
        
        by_sector = {}
        beats = 0
        surprises = []
        
        for earning in earnings:
            sector = earning.get("sector", "Unknown")
            if sector not in by_sector:
                by_sector[sector] = {"count": 0, "beats": 0, "avg_surprise": 0}
            
            by_sector[sector]["count"] += 1
            
            if earning.get("beat"):
                beats += 1
                by_sector[sector]["beats"] += 1
            
            surprise = earning.get("surprise_pct", 0)
            surprises.append(surprise)
        
        return {
            "total_earnings": len(earnings),
            "beat_count": beats,
            "beat_rate": (beats / len(earnings) * 100) if earnings else 0,
            "avg_surprise_pct": sum(surprises) / len(surprises) if surprises else 0,
            "by_sector": by_sector,
            "sectors_with_positive_beats": [s for s, d in by_sector.items() if d["beats"] > d["count"] / 2]
        }

# Singleton instance
_earnings_calendar: Optional[EarningsCalendar] = None

async def get_earnings_calendar(fmp_key: str = "") -> EarningsCalendar:
    """Get or create earnings calendar instance"""
    global _earnings_calendar
    if not _earnings_calendar:
        _earnings_calendar = EarningsCalendar(fmp_key)
        await _earnings_calendar.initialize()
    return _earnings_calendar

async def close_earnings_calendar():
    """Close earnings calendar"""
    global _earnings_calendar
    if _earnings_calendar:
        await _earnings_calendar.close()
        _earnings_calendar = None
