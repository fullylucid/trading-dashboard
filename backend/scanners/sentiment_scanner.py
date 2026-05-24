"""
Sentiment Scanner
Analyzes StockTwits sentiment, news sentiment, and social media signals
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any
import numpy as np

logger = logging.getLogger(__name__)


class SentimentScanner:
    """Scan social sentiment from StockTwits, news, and other sources"""
    
    def __init__(self):
        self.name = "sentiment"
        
    async def scan(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan for sentiment signals
        
        Args:
            symbol: Stock ticker
            data: Market data dict
            
        Returns:
            Signal dict with sentiment components
        """
        try:
            result = {
                "scanner": self.name,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "signal": "hold",
                "confidence": 0.0,
                "components": {
                    "stocktwits_bullish_ratio": 0.5,
                    "stocktwits_volume": 0,
                    "news_sentiment": 0.0,  # -1 to 1
                    "reddit_mentions": 0,
                    "sentiment_shift": 0.0,
                },
                "reason": "Sentiment analysis"
            }
            
            # Simulate StockTwits data
            # In production: connect to StockTwits API
            bullish_ratio = np.random.uniform(0.3, 0.9)
            result["components"]["stocktwits_bullish_ratio"] = bullish_ratio
            result["components"]["stocktwits_volume"] = int(np.random.randint(100, 5000))
            
            # Sentiment scoring
            if bullish_ratio > 0.65:
                result["signal"] = "buy"
                result["confidence"] = min(0.7, (bullish_ratio - 0.65) * 3)
                result["components"]["sentiment_shift"] = bullish_ratio - 0.5
            elif bullish_ratio < 0.35:
                result["signal"] = "sell"
                result["confidence"] = min(0.6, (0.35 - bullish_ratio) * 3)
                result["components"]["sentiment_shift"] = bullish_ratio - 0.5
            
            # News sentiment (mock)
            news_sentiment = np.random.uniform(-1, 1)
            result["components"]["news_sentiment"] = news_sentiment
            
            if abs(news_sentiment) > 0.6:
                result["confidence"] = max(result["confidence"], abs(news_sentiment) * 0.7)
                if news_sentiment > 0.6:
                    result["signal"] = "buy"
                else:
                    result["signal"] = "sell"
            
            # Reddit mentions (mock)
            result["components"]["reddit_mentions"] = int(np.random.randint(0, 500))
            
            result["reason"] = self._generate_reason(result)
            
            logger.info(f"Sentiment scan for {symbol}: confidence={result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Sentiment scanner error for {symbol}: {e}", exc_info=True)
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
        
        bullish_ratio = components["stocktwits_bullish_ratio"]
        reasons.append(f"StockTwits: {bullish_ratio:.0%} bullish ({components['stocktwits_volume']} posts)")
        
        news_sentiment = components["news_sentiment"]
        if news_sentiment > 0.3:
            reasons.append(f"News sentiment: Positive ({news_sentiment:.2f})")
        elif news_sentiment < -0.3:
            reasons.append(f"News sentiment: Negative ({news_sentiment:.2f})")
        else:
            reasons.append("News sentiment: Neutral")
        
        if components["reddit_mentions"] > 100:
            reasons.append(f"High Reddit mentions ({components['reddit_mentions']} in 24h)")
        
        return " | ".join(reasons)
