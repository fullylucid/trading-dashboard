"""
News Scanner
Analyzes recent news, earnings announcements, and major events
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
import numpy as np

logger = logging.getLogger(__name__)


class NewsScanner:
    """Scan news for trading signals"""
    
    def __init__(self):
        self.name = "news"
        self.news_cache = {}
        
    async def scan(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan for news signals
        
        Args:
            symbol: Stock ticker
            data: Market data dict
            
        Returns:
            Signal dict with news components
        """
        try:
            result = {
                "scanner": self.name,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "signal": "hold",
                "confidence": 0.0,
                "components": {
                    "recent_news_count": 0,
                    "earnings_date": None,
                    "last_earnings_surprise": 0.0,
                    "news_sentiment_avg": 0.0,
                    "major_catalyst": False,
                },
                "reason": "News analysis"
            }
            
            # Mock news data
            # In production: connect to NewsAPI, Finnhub news, Seeking Alpha, etc.
            
            recent_news = np.random.randint(0, 10)
            result["components"]["recent_news_count"] = recent_news
            
            if recent_news > 5:
                # Multiple news items suggests activity
                news_sentiment = np.random.uniform(-0.5, 0.8)
                result["components"]["news_sentiment_avg"] = news_sentiment
                
                if news_sentiment > 0.5:
                    result["signal"] = "buy"
                    result["confidence"] = 0.6
                elif news_sentiment < -0.3:
                    result["signal"] = "sell"
                    result["confidence"] = 0.55
            
            # Check for earnings
            days_to_earnings = np.random.randint(-30, 120)
            if -7 <= days_to_earnings <= 7:
                result["components"]["earnings_date"] = (datetime.utcnow() + timedelta(days=days_to_earnings)).isoformat()
                result["components"]["major_catalyst"] = True
                result["confidence"] = 0.45  # Earnings = elevated uncertainty
            
            result["reason"] = self._generate_reason(result)
            
            logger.info(f"News scan for {symbol}: confidence={result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"News scanner error for {symbol}: {e}", exc_info=True)
            return {
                "scanner": self.name,
                "symbol": symbol,
                "signal": "hold",
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _generate_reason(self, result: Dict[str, Any]) -> str:
        """Generate human-readable explanation"""
        components = result["components"]
        reasons = []
        
        news_count = components["recent_news_count"]
        if news_count > 0:
            reasons.append(f"{news_count} recent news items")
        
        if components["earnings_date"]:
            earnings_str = components["earnings_date"][:10]
            reasons.append(f"Earnings on {earnings_str}")
        
        sentiment = components["news_sentiment_avg"]
        if sentiment > 0.3:
            reasons.append(f"News sentiment: Positive ({sentiment:.2f})")
        elif sentiment < -0.2:
            reasons.append(f"News sentiment: Negative ({sentiment:.2f})")
        
        if not reasons:
            reasons.append("No significant news activity")
        
        return " | ".join(reasons)
