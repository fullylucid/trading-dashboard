"""
News Aggregator - Fetches and aggregates market news, earnings news, and company-specific news

Data sources:
- Alpha Vantage News API
- Finnhub News API
- Market news feeds
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import aiohttp
from collections import defaultdict

logger = logging.getLogger(__name__)

class NewsAggregator:
    """Aggregates news from multiple sources"""
    
    def __init__(self, alpha_vantage_key: str = "", finnhub_key: str = ""):
        self.alpha_vantage_key = alpha_vantage_key
        self.finnhub_key = finnhub_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, List[Dict[str, Any]]] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(minutes=15)  # 15 minute cache
    
    async def initialize(self):
        """Initialize async session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache is still valid"""
        if key not in self.cache_time:
            return False
        return datetime.now() - self.cache_time[key] < self.cache_ttl
    
    async def fetch_symbol_news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch news for specific symbol
        
        Returns: List of news articles with title, summary, source, timestamp, sentiment
        """
        cache_key = f"news_{symbol}"
        
        if self._is_cache_valid(cache_key):
            return self.cache[cache_key]
        
        await self.initialize()
        articles = []
        
        try:
            # Try Finnhub API for company news
            if self.finnhub_key:
                async with self.session.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={
                        "symbol": symbol,
                        "from": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                        "to": datetime.now().strftime("%Y-%m-%d"),
                        "token": self.finnhub_key
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for article in data[:limit]:
                            articles.append({
                                "title": article.get("headline", ""),
                                "summary": article.get("summary", ""),
                                "source": article.get("source", ""),
                                "url": article.get("url", ""),
                                "timestamp": article.get("datetime", ""),
                                "image": article.get("image", ""),
                                "related": article.get("related", []),
                                "sentiment": self._estimate_sentiment(article.get("summary", "")),
                                "category": article.get("category", "general")
                            })
        except Exception as e:
            logger.error(f"Finnhub error for {symbol}: {str(e)}")
        
        # Cache results
        self.cache[cache_key] = articles
        self.cache_time[cache_key] = datetime.now()
        
        return articles
    
    async def fetch_market_news(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Fetch general market news"""
        cache_key = "market_news"
        
        if self._is_cache_valid(cache_key):
            return self.cache[cache_key]
        
        await self.initialize()
        articles = []
        
        try:
            # Finnhub market news
            if self.finnhub_key:
                async with self.session.get(
                    "https://finnhub.io/api/v1/news",
                    params={
                        "category": "general",
                        "minId": 0,
                        "token": self.finnhub_key
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for article in data[:limit]:
                            articles.append({
                                "title": article.get("headline", ""),
                                "summary": article.get("summary", ""),
                                "source": article.get("source", ""),
                                "url": article.get("url", ""),
                                "timestamp": article.get("datetime", ""),
                                "image": article.get("image", ""),
                                "sentiment": self._estimate_sentiment(article.get("summary", "")),
                                "category": article.get("category", "general")
                            })
        except Exception as e:
            logger.error(f"Market news fetch error: {str(e)}")
        
        self.cache[cache_key] = articles
        self.cache_time[cache_key] = datetime.now()
        
        return articles
    
    async def fetch_sector_news(self, sector: str = "Technology", limit: int = 15) -> List[Dict[str, Any]]:
        """Fetch news for specific sector"""
        cache_key = f"sector_news_{sector}"
        
        if self._is_cache_valid(cache_key):
            return self.cache[cache_key]
        
        await self.initialize()
        articles = []
        
        try:
            if self.finnhub_key:
                # Map sector names to categories that Finnhub understands
                category_map = {
                    "Technology": "technology",
                    "Healthcare": "healthcare",
                    "Financials": "finance",
                    "Energy": "energy",
                    "Materials": "materials",
                    "Industrials": "industrial",
                    "Consumer": "consumer"
                }
                
                category = category_map.get(sector, sector.lower())
                
                async with self.session.get(
                    "https://finnhub.io/api/v1/news",
                    params={
                        "category": category,
                        "minId": 0,
                        "token": self.finnhub_key
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for article in data[:limit]:
                            articles.append({
                                "title": article.get("headline", ""),
                                "summary": article.get("summary", ""),
                                "source": article.get("source", ""),
                                "url": article.get("url", ""),
                                "timestamp": article.get("datetime", ""),
                                "image": article.get("image", ""),
                                "sentiment": self._estimate_sentiment(article.get("summary", "")),
                                "category": sector
                            })
        except Exception as e:
            logger.error(f"Sector news error for {sector}: {str(e)}")
        
        self.cache[cache_key] = articles
        self.cache_time[cache_key] = datetime.now()
        
        return articles
    
    def _estimate_sentiment(self, text: str) -> str:
        """
        Simple sentiment analysis based on keywords
        Returns: 'positive', 'negative', or 'neutral'
        """
        positive_words = ['rally', 'surge', 'profit', 'beat', 'gain', 'upgrade', 'outperform',
                         'growth', 'bullish', 'strength', 'momentum', 'soars', 'climbs']
        negative_words = ['crash', 'plunge', 'loss', 'miss', 'decline', 'downgrade', 'underperform',
                         'bearish', 'weakness', 'fall', 'slump', 'tumble', 'downside']
        
        text_lower = text.lower()
        
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        else:
            return "neutral"
    
    async def group_news_by_symbol(self, symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch and group news by symbol
        
        Returns: Dict mapping symbol -> list of news articles
        """
        results = {}
        
        # Fetch all news concurrently
        tasks = [self.fetch_symbol_news(symbol, limit=5) for symbol in symbols]
        news_lists = await asyncio.gather(*tasks, return_exceptions=True)
        
        for symbol, news in zip(symbols, news_lists):
            if not isinstance(news, Exception):
                results[symbol] = news
        
        return results

# Singleton instance
_news_aggregator: Optional[NewsAggregator] = None

async def get_news_aggregator(alpha_vantage_key: str = "", finnhub_key: str = "") -> NewsAggregator:
    """Get or create news aggregator instance"""
    global _news_aggregator
    if not _news_aggregator:
        _news_aggregator = NewsAggregator(alpha_vantage_key, finnhub_key)
        await _news_aggregator.initialize()
    return _news_aggregator

async def close_news_aggregator():
    """Close news aggregator"""
    global _news_aggregator
    if _news_aggregator:
        await _news_aggregator.close()
        _news_aggregator = None
