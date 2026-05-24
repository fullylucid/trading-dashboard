"""
Signal Generation Engine
Core orchestrator for multi-scanner signal generation with Redis backing
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import numpy as np

from cache_manager import CacheManager
from scanners import (
    SmartMoneyScanner,
    OptionsScanner,
    SECScanner,
    SentimentScanner,
    ShortInterestScanner,
    QuantEnsembleScanner,
    NewsScanner,
    TechnicalScanner,
)

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """Complete signal result from all scanners"""
    id: str
    timestamp: str
    symbol: str
    signal: str  # "buy", "sell", "hold"
    confidence: float  # 0-100
    scanners_used: List[str]
    components: Dict[str, Any]
    reason: str
    alerts_sent: List[str] = None
    
    def __post_init__(self):
        if self.alerts_sent is None:
            self.alerts_sent = []
    
    def to_dict(self):
        """Convert to dictionary, excluding None fields"""
        data = asdict(self)
        if not data["alerts_sent"]:
            data["alerts_sent"] = []
        return data


class SignalEngine:
    """Orchestrate signal generation from multiple scanners"""
    
    def __init__(self, cache_manager: CacheManager, logger: logging.Logger):
        self.cache = cache_manager
        self.logger = logger
        
        # Initialize scanners
        self.scanners = {
            "smart_money": SmartMoneyScanner(),
            "options": OptionsScanner(),
            "sec": SECScanner(),
            "sentiment": SentimentScanner(),
            "short_interest": ShortInterestScanner(),
            "quant_ensemble": QuantEnsembleScanner(),
            "news": NewsScanner(),
            "technical": TechnicalScanner(),
        }
        
        # Track scanner health
        self.scanner_failures = {}
        self.circuit_breaker_threshold = 3
        
    async def generate_signal(
        self,
        symbol: str,
        market_data: Dict[str, Any],
        active_scanners: Optional[List[str]] = None,
    ) -> SignalResult:
        """
        Generate comprehensive signal from multiple scanners
        
        Args:
            symbol: Stock ticker
            market_data: Dict with price, volume, and other market data
            active_scanners: List of scanners to use (defaults to all)
            
        Returns:
            SignalResult with aggregated signals and confidence
        """
        signal_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        # Use all scanners if not specified
        if not active_scanners:
            active_scanners = list(self.scanners.keys())
        
        # Run all scanners in parallel
        scan_tasks = []
        for scanner_name in active_scanners:
            if scanner_name not in self.scanners:
                self.logger.warning(f"Scanner not found: {scanner_name}")
                continue
            
            # Check circuit breaker
            if self._is_circuit_broken(scanner_name):
                self.logger.warning(f"Scanner circuit broken: {scanner_name}")
                continue
            
            scanner = self.scanners[scanner_name]
            scan_tasks.append((scanner_name, self._run_scanner_safe(scanner, symbol, market_data)))
        
        # Gather results
        components = {}
        scan_results = []
        
        for scanner_name, task in scan_tasks:
            try:
                result = await task
                if result and result.get("signal"):
                    components[scanner_name] = result.get("components", {})
                    scan_results.append(result)
                    # Reset failure counter on success
                    self.scanner_failures[scanner_name] = 0
            except Exception as e:
                self.logger.error(f"Failed to run scanner {scanner_name}: {e}")
                self._increment_failure(scanner_name)
        
        # Aggregate signals
        aggregated = self._aggregate_signals(scan_results, symbol)
        
        # Create result
        signal = SignalResult(
            id=signal_id,
            timestamp=timestamp,
            symbol=symbol,
            signal=aggregated["signal"],
            confidence=aggregated["confidence"],
            scanners_used=[r.get("scanner", "unknown") for r in scan_results],
            components=components,
            reason=aggregated["reason"],
        )
        
        # Cache signal
        await self.cache.set(
            f"signal:{symbol}",
            json.dumps(signal.to_dict()),
            ttl=300
        )
        
        # Log to analytics (append to signals feed)
        await self._log_signal(signal)
        
        self.logger.info(
            f"Generated signal for {symbol}",
            extra={
                "signal_id": signal_id,
                "signal_type": signal.signal,
                "confidence": signal.confidence,
                "scanners_used": len(signal.scanners_used),
            }
        )
        
        return signal
    
    async def _run_scanner_safe(
        self,
        scanner: Any,
        symbol: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Run scanner with timeout and error handling"""
        try:
            result = await asyncio.wait_for(
                scanner.scan(symbol, data),
                timeout=5.0
            )
            return result
        except asyncio.TimeoutError:
            self.logger.warning(f"Scanner timeout: {scanner.name} for {symbol}")
            return None
        except Exception as e:
            self.logger.error(f"Scanner error: {scanner.name}: {e}", exc_info=True)
            return None
    
    def _aggregate_signals(self, scan_results: List[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
        """
        Aggregate multiple scanner signals
        Uses weighted voting based on confidence
        """
        if not scan_results:
            return {
                "signal": "hold",
                "confidence": 0.0,
                "reason": "No scanner results available"
            }
        
        # Weight signals by confidence
        buy_weight = 0.0
        sell_weight = 0.0
        confidence_scores = []
        
        for result in scan_results:
            signal = result.get("signal", "hold")
            confidence = result.get("confidence", 0.0)
            
            confidence_scores.append(confidence)
            
            if signal == "buy":
                buy_weight += confidence
            elif signal == "sell":
                sell_weight += confidence
        
        # Determine final signal
        if buy_weight > sell_weight + 0.1:
            final_signal = "buy"
            final_confidence = min(100, buy_weight)
        elif sell_weight > buy_weight + 0.1:
            final_signal = "sell"
            final_confidence = min(100, sell_weight)
        else:
            final_signal = "hold"
            final_confidence = np.mean(confidence_scores) if confidence_scores else 0.0
        
        # Generate aggregated reason
        reasons = []
        for result in scan_results:
            if result.get("reason"):
                reasons.append(f"{result['scanner']}: {result['reason']}")
        
        return {
            "signal": final_signal,
            "confidence": float(final_confidence),
            "reason": " | ".join(reasons) if reasons else "Aggregated scanner analysis"
        }
    
    def _is_circuit_broken(self, scanner_name: str) -> bool:
        """Check if scanner circuit breaker is activated"""
        failures = self.scanner_failures.get(scanner_name, 0)
        return failures >= self.circuit_breaker_threshold
    
    def _increment_failure(self, scanner_name: str) -> None:
        """Increment failure counter for scanner"""
        self.scanner_failures[scanner_name] = self.scanner_failures.get(scanner_name, 0) + 1
    
    async def _log_signal(self, signal: SignalResult) -> None:
        """Log signal to analytics file"""
        try:
            log_file = "/tmp/trading-dashboard/logs/signals.jsonl"
            # Append to signals log
            import aiofiles
            async with aiofiles.open(log_file, "a") as f:
                await f.write(json.dumps(signal.to_dict()) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to log signal: {e}")
    
    async def get_signal_for_symbol(self, symbol: str) -> Optional[SignalResult]:
        """Retrieve cached signal for symbol"""
        try:
            cached = await self.cache.get(f"signal:{symbol}")
            if cached:
                data = json.loads(cached)
                return SignalResult(**data)
        except Exception as e:
            self.logger.error(f"Failed to retrieve signal for {symbol}: {e}")
        return None
    
    async def get_scanner_details(self, scanner_name: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed output from specific scanner"""
        if scanner_name not in self.scanners:
            return None
        
        try:
            # Would fetch market data for symbol here
            # For now, return circuit breaker status
            return {
                "scanner": scanner_name,
                "active": not self._is_circuit_broken(scanner_name),
                "failures": self.scanner_failures.get(scanner_name, 0),
            }
        except Exception as e:
            self.logger.error(f"Failed to get scanner details: {e}")
            return None
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all scanners"""
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "scanners": {}
        }
        
        for name, scanner in self.scanners.items():
            failures = self.scanner_failures.get(name, 0)
            status["scanners"][name] = {
                "active": not self._is_circuit_broken(name),
                "failures": failures,
                "circuit_broken": self._is_circuit_broken(name),
            }
        
        return status
