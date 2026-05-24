"""
SEC Scanner
Detects significant SEC filings (Form 4, 8-K, 13-D) and insider activities
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any
import asyncio

logger = logging.getLogger(__name__)


class SECScanner:
    """Scan SEC filings for trading signals"""
    
    def __init__(self):
        self.name = "sec"
        self.last_filings_check = {}
        
    async def scan(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan for SEC filing signals
        
        Args:
            symbol: Stock ticker
            data: Market data dict
            
        Returns:
            Signal dict with SEC filing components
        """
        try:
            result = {
                "scanner": self.name,
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "signal": "hold",
                "confidence": 0.0,
                "components": {
                    "form_4_buys": 0,
                    "form_4_sells": 0,
                    "form_8k_recent": False,
                    "form_13d_activity": False,
                    "insider_confidence": 0.0,
                },
                "reason": "SEC filing analysis"
            }
            
            # In production: fetch from SEC EDGAR API or service
            # For now: simulate based on symbol/data
            
            # Mock Form 4 insider transactions
            if data.get("volume_spike"):
                # Higher likelihood of insider activity with volume spike
                result["components"]["form_4_buys"] = 2 if hash(symbol) % 3 == 0 else 1
                result["components"]["insider_confidence"] = 0.65
                result["signal"] = "buy"
                result["confidence"] = 0.65
            
            # Mock Form 8-K detection (would check filing dates)
            last_check = self.last_filings_check.get(symbol)
            if not last_check or (datetime.utcnow() - last_check).days > 1:
                if hash(symbol) % 7 == 0:
                    result["components"]["form_8k_recent"] = True
                    result["confidence"] = 0.55
                self.last_filings_check[symbol] = datetime.utcnow()
            
            result["reason"] = self._generate_reason(result)
            
            logger.info(f"SEC scan for {symbol}: confidence={result['confidence']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"SEC scanner error for {symbol}: {e}", exc_info=True)
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
        
        if components["form_4_buys"] > 0:
            reasons.append(f"Form 4: {components['form_4_buys']} insider purchases detected")
        
        if components["form_4_sells"] > 0:
            reasons.append(f"Form 4: {components['form_4_sells']} insider sales detected")
        
        if components["form_8k_recent"]:
            reasons.append("Recent 8-K filing (significant event)")
        
        if components["form_13d_activity"]:
            reasons.append("Form 13-D activity (significant position change)")
        
        if not reasons:
            reasons.append("No significant SEC filing activity")
        
        return " | ".join(reasons)
