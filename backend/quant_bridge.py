"""
Bridge to quant-toolkit.py for signal generation
Integrates with existing Tradeskeebot quantitative analysis
"""

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from cache_manager import CacheManager

class QuantSignalBridge:
    """Call quant-toolkit.py and parse results for signals"""
    
    def __init__(
        self, 
        quant_toolkit_path: str,
        logger: logging.Logger,
        cache_manager: CacheManager
    ):
        self.quant_toolkit_path = Path(quant_toolkit_path)
        self.logger = logger
        self.cache = cache_manager
        
        # Verify toolkit exists
        if not self.quant_toolkit_path.exists():
            self.logger.warning(f"Quant toolkit not found at {self.quant_toolkit_path}")
        
        # HMM regime state cache
        self.regime_cache: Optional[Dict] = None
        self.regime_cache_time: Optional[datetime] = None
        self.regime_cache_ttl = 300  # 5 minutes
    
    async def generate_signal(self, symbol: str, ohlcv: Dict) -> Dict:
        """
        Generate trading signal for a symbol
        Calls quant-toolkit.py with OHLCV data
        """
        try:
            # Check cache first
            cached = await self.cache.get(f"signal:{symbol}")
            if cached:
                return json.loads(cached)
            
            # Call quant toolkit
            result = await self._call_quant_toolkit(symbol, ohlcv)
            
            if not result:
                # Return neutral signal on error
                return self._neutral_signal(symbol)
            
            # Parse and structure signal
            signal = self._parse_quant_result(symbol, result)
            
            # Log signal
            self.logger.info(
                f"Generated signal for {symbol}",
                extra={
                    "symbol": symbol,
                    "signal_type": signal.get("signal_type"),
                    "confidence": signal.get("aggregate_confidence")
                }
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Failed to generate signal for {symbol}: {e}", exc_info=True)
            return self._neutral_signal(symbol)
    
    async def _call_quant_toolkit(self, symbol: str, ohlcv: Dict) -> Optional[Dict]:
        """
        Call quant-toolkit.py subprocess
        Returns parsed JSON result
        """
        if not self.quant_toolkit_path.exists():
            return None
        
        try:
            # Prepare input JSON
            input_data = json.dumps({
                "symbol": symbol,
                "ohlcv": ohlcv
            })
            
            # Call subprocess
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(self.quant_toolkit_path),
                "analyze",
                "--symbol", symbol,
                "--format", "json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                timeout=10
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data.encode()),
                timeout=10
            )
            
            if process.returncode != 0:
                self.logger.warning(
                    f"Quant toolkit error for {symbol}: {stderr.decode()}"
                )
                return None
            
            # Parse output
            output = stdout.decode().strip()
            if output:
                return json.loads(output)
            
            return None
            
        except asyncio.TimeoutError:
            self.logger.warning(f"Quant toolkit timeout for {symbol}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to call quant toolkit: {e}", exc_info=True)
            return None
    
    def _parse_quant_result(self, symbol: str, result: Dict) -> Dict:
        """Parse quant toolkit JSON result into signal format"""
        
        # Extract strategy scores
        strategies = result.get("strategies", {})
        
        momentum_score = strategies.get("momentum", {}).get("score", 0)
        momentum_conf = strategies.get("momentum", {}).get("confidence", 0)
        
        reversion_score = strategies.get("reversion", {}).get("score", 0)
        reversion_conf = strategies.get("reversion", {}).get("confidence", 0)
        
        volatility = strategies.get("volatility", {})
        volatility_score = volatility.get("score", 0)
        volatility_regime = volatility.get("regime", "unknown")
        
        pattern = strategies.get("patterns", {})
        pattern_score = pattern.get("score", 0)
        
        regime = strategies.get("regime", {})
        regime_score = regime.get("score", 0)
        
        correlation = strategies.get("correlation", {})
        correlation_score = correlation.get("score", 0)
        
        leading = strategies.get("leading_indicators", {})
        leading_score = leading.get("score", 0)
        
        # Calculate aggregate confidence
        all_scores = [
            momentum_conf, reversion_conf,
            pattern.get("confidence", 0),
            regime.get("confidence", 0),
            correlation.get("confidence", 0),
            leading.get("confidence", 0)
        ]
        aggregate_confidence = sum(all_scores) / len(all_scores) if all_scores else 0.5
        
        # Determine signal type
        signal_type = self._determine_signal_type(
            momentum_score, reversion_score, pattern_score, regime_score
        )
        
        trigger_reason = result.get("trigger_reason", "automated_analysis")
        
        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "momentum_score": float(momentum_score),
            "momentum_confidence": float(momentum_conf),
            "reversion_score": float(reversion_score),
            "reversion_confidence": float(reversion_conf),
            "volatility_regime": str(volatility_regime),
            "volatility_score": float(volatility_score),
            "pattern_score": float(pattern_score),
            "regime_score": float(regime_score),
            "correlation_score": float(correlation_score),
            "leading_indicator_score": float(leading_score),
            "aggregate_confidence": float(aggregate_confidence),
            "signal_type": signal_type,
            "trigger_reason": str(trigger_reason)
        }
    
    def _determine_signal_type(
        self, 
        momentum: float, 
        reversion: float, 
        pattern: float,
        regime: float
    ) -> str:
        """Determine buy/sell/neutral signal from scores"""
        
        # Weighted scoring: momentum > pattern > regime > reversion
        weighted_score = (
            momentum * 0.4 +
            pattern * 0.25 +
            regime * 0.2 +
            reversion * 0.15
        )
        
        if weighted_score > 0.3:
            return "buy"
        elif weighted_score < -0.3:
            return "sell"
        else:
            return "neutral"
    
    def _neutral_signal(self, symbol: str) -> Dict:
        """Return neutral signal (no clear direction)"""
        return {
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "momentum_score": 0,
            "momentum_confidence": 0,
            "reversion_score": 0,
            "reversion_confidence": 0,
            "volatility_regime": "unknown",
            "volatility_score": 0,
            "pattern_score": 0,
            "regime_score": 0,
            "correlation_score": 0,
            "leading_indicator_score": 0,
            "aggregate_confidence": 0,
            "signal_type": "neutral",
            "trigger_reason": "error_or_no_signal"
        }
    
    async def get_regime_state(self) -> Dict:
        """
        Get current market regime (HMM phase, volatility, etc)
        Calls quant toolkit for regime analysis
        """
        
        # Check cache
        now = datetime.utcnow()
        if (self.regime_cache and 
            self.regime_cache_time and 
            (now - self.regime_cache_time).total_seconds() < self.regime_cache_ttl):
            return self.regime_cache
        
        try:
            # Call quant toolkit for regime
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(self.quant_toolkit_path),
                "regime",
                "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                timeout=10
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=10
            )
            
            if process.returncode == 0:
                result = json.loads(stdout.decode())
                self.regime_cache = result
                self.regime_cache_time = now
                return result
            
        except Exception as e:
            self.logger.warning(f"Failed to get regime state: {e}")
        
        # Return default regime
        return {
            "hmm_phase": 0,
            "volatility_regime": "normal",
            "market_heat": 0.5,
            "trend_direction": "neutral",
            "estimated_probability": 0.33
        }
