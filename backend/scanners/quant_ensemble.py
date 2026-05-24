"""
Quant Ensemble Scanner
Wraps the existing QuantToolkit for multi-strategy signal generation
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)


class QuantEnsembleScanner:
    """Ensemble of quantitative strategies for signal generation"""
    
    def __init__(self):
        self.name = "quant_ensemble"
        self._toolkit: Optional[Any] = None
        
    async def scan(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan using ensemble quant strategies
        
        Args:
            symbol: Stock ticker
            data: Market data dict with prices, volumes, etc.
            
        Returns:
            Signal dict with quant ensemble components
        """
        try:
            result = {
                "scanner": self.name,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "signal": "hold",
                "confidence": 0.0,
                "components": {
                    "momentum_score": 0.5,
                    "mean_reversion_score": 0.5,
                    "volatility_regime": "normal",
                    "pattern_detection": "none",
                    "strategy_votes": {},
                },
                "reason": "Quantitative ensemble analysis"
            }
            
            # Extract price data
            prices = data.get("prices", [])
            volumes = data.get("volumes", [])
            
            if not prices or len(prices) < 20:
                logger.warning(f"Insufficient price data for quant scan: {symbol}")
                return result
            
            prices_array = np.array(prices, dtype=float)
            volumes_array = np.array(volumes, dtype=float) if volumes else None
            
            # Strategy 1: Momentum
            momentum = self._momentum_strategy(prices_array)
            result["components"]["momentum_score"] = momentum
            result["components"]["strategy_votes"]["momentum"] = "buy" if momentum > 0.6 else ("sell" if momentum < 0.4 else "hold")
            
            # Strategy 2: Mean Reversion
            mean_reversion = self._mean_reversion_strategy(prices_array)
            result["components"]["mean_reversion_score"] = mean_reversion
            result["components"]["strategy_votes"]["mean_reversion"] = "buy" if mean_reversion > 0.6 else ("sell" if mean_reversion < 0.4 else "hold")
            
            # Strategy 3: Volatility Analysis
            volatility_regime = self._volatility_regime(prices_array)
            result["components"]["volatility_regime"] = volatility_regime
            
            # Strategy 4: Pattern Detection
            pattern = self._pattern_detection(prices_array)
            result["components"]["pattern_detection"] = pattern
            result["components"]["strategy_votes"]["patterns"] = "buy" if pattern in ["gap_and_go", "breakout"] else ("sell" if pattern == "breakdown" else "hold")
            
            # Strategy 5: Volume Analysis
            if volumes_array is not None:
                vol_signal = self._volume_strategy(prices_array, volumes_array)
                result["components"]["strategy_votes"]["volume"] = vol_signal
            
            # Aggregate signal
            votes = result["components"]["strategy_votes"]
            buy_votes = sum(1 for v in votes.values() if v == "buy")
            sell_votes = sum(1 for v in votes.values() if v == "sell")
            
            if buy_votes > sell_votes:
                result["signal"] = "buy"
                result["confidence"] = min(0.85, buy_votes / max(len(votes), 1) * 0.9)
            elif sell_votes > buy_votes:
                result["signal"] = "sell"
                result["confidence"] = min(0.80, sell_votes / max(len(votes), 1) * 0.85)
            else:
                result["signal"] = "hold"
                result["confidence"] = 0.5
            
            result["reason"] = self._generate_reason(result)
            
            logger.info(f"Quant ensemble scan for {symbol}: confidence={result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Quant ensemble scanner error for {symbol}: {e}", exc_info=True)
            return {
                "scanner": self.name,
                "symbol": symbol,
                "signal": "hold",
                "confidence": 0.0,
                "error": str(e)
            }
    
    def _momentum_strategy(self, prices: np.ndarray) -> float:
        """Calculate momentum score (0-1)"""
        if len(prices) < 10:
            return 0.5
        
        recent_change = (prices[-1] - prices[-10]) / prices[-10]
        momentum = max(0, min(1, (recent_change + 0.1) / 0.2))  # Normalize
        return float(momentum)
    
    def _mean_reversion_strategy(self, prices: np.ndarray) -> float:
        """Calculate mean reversion score (0-1)"""
        if len(prices) < 20:
            return 0.5
        
        ma_20 = np.mean(prices[-20:])
        std_dev = np.std(prices[-20:])
        
        distance_from_mean = abs(prices[-1] - ma_20) / std_dev if std_dev > 0 else 0
        
        # Extreme moves suggest reversion
        reversion_score = min(1.0, distance_from_mean / 2.0)
        return float(reversion_score)
    
    def _volatility_regime(self, prices: np.ndarray) -> str:
        """Determine volatility regime"""
        if len(prices) < 20:
            return "normal"
        
        # Calculate percentage changes manually
        recent_returns = np.diff(prices[-20:]) / prices[-20:-1]
        recent_volatility = np.std(recent_returns)
        
        long_returns = np.diff(prices[-60:]) / prices[-60:-1] if len(prices) >= 60 else recent_returns
        long_volatility = np.std(long_returns)
        
        ratio = recent_volatility / long_volatility if long_volatility > 0 else 1.0
        
        if ratio > 1.3:
            return "high"
        elif ratio < 0.7:
            return "low"
        return "normal"
    
    def _pattern_detection(self, prices: np.ndarray) -> str:
        """Detect technical patterns"""
        if len(prices) < 5:
            return "none"
        
        # Check for gap (price jump)
        gap = abs(prices[-1] - prices[-2]) / prices[-2]
        if gap > 0.05:
            momentum = (prices[-1] - prices[-3]) / prices[-3]
            if momentum > 0.03:
                return "gap_and_go"
            return "gap_reversal"
        
        # Check for breakout
        sma_20 = np.mean(prices[-20:])
        if prices[-1] > sma_20 * 1.02 and prices[-2] < sma_20:
            return "breakout"
        elif prices[-1] < sma_20 * 0.98 and prices[-2] > sma_20:
            return "breakdown"
        
        return "none"
    
    def _volume_strategy(self, prices: np.ndarray, volumes: np.ndarray) -> str:
        """Analyze volume for confirmation"""
        if len(volumes) < 5:
            return "hold"
        
        recent_vol = np.mean(volumes[-5:])
        avg_vol = np.mean(volumes[-20:])
        
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
        
        price_change = (prices[-1] - prices[-5]) / prices[-5]
        
        if vol_ratio > 1.3 and price_change > 0:
            return "buy"
        elif vol_ratio > 1.3 and price_change < 0:
            return "sell"
        
        return "hold"
    
    def _generate_reason(self, result: Dict[str, Any]) -> str:
        """Generate human-readable explanation"""
        components = result["components"]
        reasons = []
        
        momentum = components["momentum_score"]
        reasons.append(f"Momentum: {momentum:.0%}")
        
        reversion = components["mean_reversion_score"]
        reasons.append(f"Mean reversion: {reversion:.0%}")
        
        volatility = components["volatility_regime"]
        reasons.append(f"Volatility: {volatility}")
        
        pattern = components["pattern_detection"]
        if pattern != "none":
            reasons.append(f"Pattern: {pattern}")
        
        votes = components["strategy_votes"]
        buy_count = sum(1 for v in votes.values() if v == "buy")
        reasons.append(f"Consensus: {buy_count}/{len(votes)} strategies bullish")
        
        return " | ".join(reasons)
