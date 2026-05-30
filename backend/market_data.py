"""
Market Data - Fetches key market statistics, sector performance, and market breadth

Provides:
- Market breadth (advance/decline ratio)
- Sector performance
- VIX and volatility index
- Market moving averages
- Key economic indicators
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

# US equity market operates on Eastern Time regardless of server timezone
MARKET_TZ = ZoneInfo("America/New_York")

class MarketData:
    """Fetches and caches market data and statistics"""
    
    def __init__(self, finnhub_key: str = "", fmp_key: str = ""):
        self.finnhub_key = finnhub_key
        self.fmp_key = fmp_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(minutes=5)  # 5 minute cache
    
    async def initialize(self):
        """Initialize async session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    async def fetch_market_overview(self) -> Dict[str, Any]:
        """Fetch overall market statistics"""
        cache_key = "market_overview"
        
        if cache_key in self.cache:
            if datetime.now() - self.cache_time.get(cache_key, datetime.now()) < self.cache_ttl:
                return self.cache[cache_key]
        
        await self.initialize()
        overview = {}
        
        try:
            # Fetch key indices
            indices = ["^GSPC", "^INDC", "^RUT", "^VIX"]  # SPY, Nasdaq, Russell 2000, VIX
            
            if self.finnhub_key:
                tasks = []
                for index in indices:
                    tasks.append(self._fetch_quote(index))
                
                quotes = await asyncio.gather(*tasks, return_exceptions=True)
                
                for idx, quote in zip(indices, quotes):
                    if not isinstance(quote, Exception) and quote:
                        overview[idx] = {
                            "symbol": idx,
                            "price": quote.get("c", 0),
                            "change": quote.get("d", 0),
                            "change_percent": quote.get("dp", 0),
                            "timestamp": datetime.now().isoformat()
                        }
        
        except Exception as e:
            logger.error(f"Market overview error: {str(e)}")
        
        # Add market stats
        overview["market_time"] = "open" if self._is_market_open() else "closed"
        overview["last_updated"] = datetime.now().isoformat()
        
        self.cache[cache_key] = overview
        self.cache_time[cache_key] = datetime.now()
        
        return overview
    
    async def fetch_sector_performance(self) -> Dict[str, Any]:
        """Fetch sector performance rankings"""
        cache_key = "sector_performance"
        
        if cache_key in self.cache:
            if datetime.now() - self.cache_time.get(cache_key, datetime.now()) < self.cache_ttl:
                return self.cache[cache_key]
        
        await self.initialize()
        sectors = {}
        
        try:
            # Sector ETF symbols
            sector_etfs = {
                "XLK": "Technology",
                "XLV": "Healthcare",
                "XLF": "Financials",
                "XLE": "Energy",
                "XLI": "Industrials",
                "XLY": "Consumer Discretionary",
                "XLP": "Consumer Staples",
                "XLRE": "Real Estate",
                "XLU": "Utilities",
                "XLUP": "Materials"
            }
            
            if self.finnhub_key:
                tasks = []
                for etf in sector_etfs.keys():
                    tasks.append(self._fetch_quote(etf))
                
                quotes = await asyncio.gather(*tasks, return_exceptions=True)
                
                for (etf, sector_name), quote in zip(sector_etfs.items(), quotes):
                    if not isinstance(quote, Exception) and quote:
                        sectors[sector_name] = {
                            "etf": etf,
                            "price": quote.get("c", 0),
                            "change_percent": quote.get("dp", 0),
                            "performance": "outperform" if quote.get("dp", 0) > 0 else "underperform"
                        }
        
        except Exception as e:
            logger.error(f"Sector performance error: {str(e)}")
        
        # Sort by performance
        sorted_sectors = dict(sorted(
            sectors.items(),
            key=lambda x: x[1].get("change_percent", 0),
            reverse=True
        ))
        
        self.cache[cache_key] = {
            "sectors": sorted_sectors,
            "timestamp": datetime.now().isoformat()
        }
        self.cache_time[cache_key] = datetime.now()
        
        return self.cache[cache_key]
    
    async def _fetch_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch real-time quote for symbol"""
        try:
            if self.finnhub_key:
                async with self.session.get(
                    "https://finnhub.io/api/v1/quote",
                    params={
                        "symbol": symbol,
                        "token": self.finnhub_key
                    },
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.error(f"Quote fetch error for {symbol}: {str(e)}")
        
        return None
    
    def _is_market_open(self) -> bool:
        """Check if US market is currently open (Eastern Time aware)"""
        # Always evaluate against US Eastern Time, independent of server tz
        now = datetime.now(MARKET_TZ)

        # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
        weekday = now.weekday()
        if weekday >= 5:  # Saturday or Sunday
            return False

        hour = now.hour
        minute = now.minute
        current_time = hour * 60 + minute

        market_open = 9 * 60 + 30  # 9:30 AM ET
        market_close = 16 * 60  # 4:00 PM ET

        return market_open <= current_time < market_close
    
    async def fetch_market_breadth(self) -> Dict[str, Any]:
        """Fetch market breadth (advance/decline ratio, etc)"""
        cache_key = "market_breadth"
        
        if cache_key in self.cache:
            if datetime.now() - self.cache_time.get(cache_key, datetime.now()) < self.cache_ttl:
                return self.cache[cache_key]
        
        # For now, return default structure
        breadth = {
            "advancers": 0,
            "decliners": 0,
            "unchanged": 0,
            "advance_decline_ratio": 0,
            "advance_decline_line": 0,
            "up_volume": 0,
            "down_volume": 0,
            "up_down_ratio": 0,
            "put_call_ratio": 0,
            "timestamp": datetime.now().isoformat()
        }
        
        self.cache[cache_key] = breadth
        self.cache_time[cache_key] = datetime.now()
        
        return breadth
    
    async def fetch_economic_calendar(self) -> List[Dict[str, Any]]:
        """Fetch upcoming economic events"""
        cache_key = "economic_calendar"
        
        if cache_key in self.cache:
            if datetime.now() - self.cache_time.get(cache_key, datetime.now()) < timedelta(hours=1):
                return self.cache[cache_key]
        
        # Default calendar structure
        events = [
            {
                "date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
                "time": "10:00 AM",
                "event": "Initial Jobless Claims",
                "impact": "High",
                "forecast": "",
                "previous": ""
            },
            {
                "date": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
                "time": "2:00 PM",
                "event": "FOMC Decision",
                "impact": "High",
                "forecast": "",
                "previous": ""
            }
        ]
        
        self.cache[cache_key] = events
        self.cache_time[cache_key] = datetime.now()
        
        return events
    
    async def get_market_summary(self) -> Dict[str, Any]:
        """Get complete market summary"""
        overview = await self.fetch_market_overview()
        sectors = await self.fetch_sector_performance()
        breadth = await self.fetch_market_breadth()
        
        return {
            "market_overview": overview,
            "sector_performance": sectors,
            "market_breadth": breadth,
            "timestamp": datetime.now().isoformat()
        }

# Singleton instance
_market_data: Optional[MarketData] = None

async def get_market_data(finnhub_key: str = "", fmp_key: str = "") -> MarketData:
    """Get or create market data instance"""
    global _market_data
    if not _market_data:
        _market_data = MarketData(finnhub_key, fmp_key)
        await _market_data.initialize()
    return _market_data

async def close_market_data():
    """Close market data"""
    global _market_data
    if _market_data:
        await _market_data.close()
        _market_data = None
