"""
Short Interest Scanner
Detects short interest changes, borrow availability, and short squeeze potential
"""

import logging
from datetime import datetime
from typing import Dict, Any
import numpy as np

logger = logging.getLogger(__name__)


class ShortInterestScanner:
    """Scan short interest data for signals"""
    
    def __init__(self):
        self.name = "short_interest"
        self.previous_float = {}
        
    async def scan(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan for short interest signals
        
        Args:
            symbol: Stock ticker
            data: Market data dict
            
        Returns:
            Signal dict with short interest components
        """
        try:
            result = {
                "scanner": self.name,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "signal": "hold",
                "confidence": 0.0,
                "components": {
                    "short_float_percent": 0.0,
                    "short_shares": 0,
                    "borrow_fee": 0.0,
                    "borrow_availability": 0,  # shares available to borrow
                    "short_squeeze_risk": False,
                },
                "reason": "Short interest analysis"
            }
            
            # Mock short interest data
            # In production: connect to Fintel, Iborrowdesk, Interactive Brokers, etc.
            
            short_float = np.random.uniform(0.05, 0.35)  # 5-35% short float
            result["components"]["short_float_percent"] = short_float
            result["components"]["short_shares"] = int(data.get("shares_outstanding", 100_000_000) * short_float)
            
            # Short squeeze detection: high short float + low borrow availability
            borrow_avail = np.random.randint(10000, 500000)
            result["components"]["borrow_availability"] = borrow_avail
            
            if short_float > 0.20 and borrow_avail < 50000:
                result["components"]["short_squeeze_risk"] = True
                result["signal"] = "buy"
                result["confidence"] = 0.65
                result["components"]["borrow_fee"] = np.random.uniform(0.01, 0.1)
            elif short_float > 0.25:
                result["signal"] = "buy"
                result["confidence"] = 0.55
                result["components"]["borrow_fee"] = np.random.uniform(0.001, 0.05)
            
            # Borrow fee (higher = more expensive shorts)
            result["components"]["borrow_fee"] = np.random.uniform(0.001, 0.08)
            
            result["reason"] = self._generate_reason(result)
            
            logger.info(f"Short interest scan for {symbol}: confidence={result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"Short interest scanner error for {symbol}: {e}", exc_info=True)
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
        
        short_pct = components["short_float_percent"]
        reasons.append(f"Short float: {short_pct:.1%}")
        
        if components["short_squeeze_risk"]:
            reasons.append("⚠️ SHORT SQUEEZE RISK: High short interest + low borrow availability")
        
        borrow_fee = components["borrow_fee"]
        if borrow_fee > 0.05:
            reasons.append(f"High borrow fee: {borrow_fee:.2%} (expensive shorts)")
        elif borrow_fee < 0.01:
            reasons.append("Low borrow fee (easy shorts)")
        
        avail = components["borrow_availability"]
        if avail < 50000:
            reasons.append(f"Low borrow availability: only {avail:,} shares")
        
        return " | ".join(reasons)
