"""
Technical Scanner
Analyzes technical patterns, moving averages, support/resistance levels
"""

import logging
from datetime import datetime
from typing import Dict, Any
import numpy as np

logger = logging.getLogger(__name__)


class TechnicalScanner:
    """Scan technical indicators for trading signals"""
    
    def __init__(self):
        self.name = "technical"
        
    async def scan(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan for technical signals
        
        Args:
            symbol: Stock ticker
            data: Market data dict with prices, volumes, etc.
            
        Returns:
            Signal dict with technical components
        """
        try:
            result = {
                "scanner": self.name,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "signal": "hold",
                "confidence": 0.0,
                "components": {
                    "moving_average_signal": 0.0,  # -1 to 1 (cross signal)
                    "rsi_value": 50.0,
                    "macd_signal": 0.0,
                    "support_resistance_break": False,
                    "pattern_score": 0.0,
                },
                "reason": "Technical analysis"
            }
            
            # Extract price data
            prices = data.get("prices", [])
            if not prices or len(prices) < 50:
                logger.warning(f"Insufficient price data for technical scan: {symbol}")
                return result
            
            prices_array = np.array(prices, dtype=float)
            
            # Moving average crossover
            ma_20 = np.mean(prices_array[-20:])
            ma_50 = np.mean(prices_array[-50:])
            ma_200 = np.mean(prices_array[-200:]) if len(prices_array) >= 200 else ma_50

            current = prices_array[-1]

            # Price position relative to MAs
            ma_signal = 0.0
            if current > ma_20 > ma_50 and current > ma_200:
                ma_signal = 0.8  # Strong uptrend (above all MAs incl. 200-DMA)
                result["signal"] = "buy"
                result["confidence"] = 0.6
            elif current < ma_20 < ma_50 and current < ma_200:
                ma_signal = -0.8  # Strong downtrend (below all MAs incl. 200-DMA)
                result["signal"] = "sell"
                result["confidence"] = 0.6
            elif current > ma_20:
                ma_signal = 0.3
            
            result["components"]["moving_average_signal"] = ma_signal
            
            # RSI (simplified)
            rsi = self._calculate_rsi(prices_array)
            result["components"]["rsi_value"] = rsi
            
            if rsi < 30:
                result["signal"] = "buy"
                result["confidence"] = max(result["confidence"], 0.55)
            elif rsi > 70:
                result["signal"] = "sell"
                result["confidence"] = max(result["confidence"], 0.55)
            
            # MACD (simplified)
            macd = self._calculate_macd(prices_array)
            result["components"]["macd_signal"] = macd
            
            if macd > 0:
                result["signal"] = "buy" if result["signal"] == "hold" else result["signal"]
                result["confidence"] = max(result["confidence"], 0.5)
            elif macd < 0:
                result["signal"] = "sell" if result["signal"] == "hold" else result["signal"]
            
            result["reason"] = self._generate_reason(result)
            
            logger.info(f"Technical scan for {symbol}: confidence={result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Technical scanner error for {symbol}: {e}", exc_info=True)
            return {
                "scanner": self.name,
                "symbol": symbol,
                "signal": "hold",
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices)
        seed = deltas[:period + 1]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        
        rs = up / down if down != 0 else 1.0
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    
    def _calculate_macd(self, prices: np.ndarray) -> float:
        """Calculate MACD (simplified)"""
        if len(prices) < 26:
            return 0.0
        
        ema_12 = np.mean(prices[-12:])
        ema_26 = np.mean(prices[-26:])
        macd_line = ema_12 - ema_26
        return float(macd_line)
    
    def _generate_reason(self, result: Dict[str, Any]) -> str:
        """Generate human-readable explanation"""
        components = result["components"]
        reasons = []
        
        ma_signal = components["moving_average_signal"]
        if ma_signal > 0.5:
            reasons.append("Price above MA20/50 (uptrend)")
        elif ma_signal < -0.5:
            reasons.append("Price below MA20/50 (downtrend)")
        
        rsi = components["rsi_value"]
        if rsi < 30:
            reasons.append(f"RSI oversold: {rsi:.0f}")
        elif rsi > 70:
            reasons.append(f"RSI overbought: {rsi:.0f}")
        else:
            reasons.append(f"RSI: {rsi:.0f}")
        
        if components["macd_signal"] > 0:
            reasons.append("MACD: Bullish")
        elif components["macd_signal"] < 0:
            reasons.append("MACD: Bearish")
        
        return " | ".join(reasons)
