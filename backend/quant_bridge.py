"""
Bridge to QuantToolkit for signal generation.
Integrates with the vendored Tradeskeebot quantitative analysis module.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from cache_manager import CacheManager
from quant_toolkit import QuantToolkit


class QuantSignalBridge:
    """Call QuantToolkit methods in a thread pool to generate signals."""

    def __init__(
        self,
        logger: logging.Logger,
        cache_manager: CacheManager,
        quant_toolkit_path: Optional[str] = None,  # retained for backward-compat; unused
    ):
        self.logger = logger
        self.cache = cache_manager
        self._toolkit: Optional[QuantToolkit] = None
        self._toolkit_loaded = False

        # HMM regime state cache
        self.regime_cache: Optional[Dict] = None
        self.regime_cache_time: Optional[datetime] = None
        self.regime_cache_ttl = 300  # 5 minutes

    def _load_toolkit(self) -> None:
        """Instantiate QuantToolkit (lazy, idempotent)."""
        if self._toolkit_loaded:
            return
        self._toolkit_loaded = True
        try:
            self._toolkit = QuantToolkit()
            self.logger.info("QuantToolkit loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to instantiate QuantToolkit: {e}", exc_info=True)
            self._toolkit = None

    async def generate_signal(self, symbol: str, ohlcv: Dict) -> Dict:
        """Generate trading signal for a symbol from OHLCV data."""
        try:
            # Check cache first
            cached = await self.cache.get(f"signal:{symbol}")
            if cached:
                return json.loads(cached)

            result = await self._call_quant_toolkit(symbol, ohlcv)
            if not result:
                return self._neutral_signal(symbol)

            signal = self._parse_quant_result(symbol, result)
            self.logger.info(
                f"Generated signal for {symbol}",
                extra={
                    "symbol": symbol,
                    "signal_type": signal.get("signal_type"),
                    "confidence": signal.get("aggregate_confidence"),
                },
            )
            return signal

        except Exception as e:
            self.logger.error(f"Failed to generate signal for {symbol}: {e}", exc_info=True)
            return self._neutral_signal(symbol)

    async def _call_quant_toolkit(self, symbol: str, ohlcv: Dict) -> Optional[Dict]:
        """Call QuantToolkit.ensemble_signal directly via in-process import."""
        self._load_toolkit()
        if not self._toolkit:
            return None

        try:
            close_prices = ohlcv.get("close", [])
            volume_data = ohlcv.get("volume", [])

            if not close_prices or not volume_data:
                self.logger.warning(f"Missing price/volume data for {symbol}")
                return None

            prices_array = np.array(close_prices, dtype=float)
            volume_array = np.array(volume_data, dtype=float)

            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._toolkit.ensemble_signal,
                    symbol,
                    prices_array,
                    volume_array,
                ),
                timeout=10,
            )

            if not result:
                return None

            # Transform toolkit's ensemble_signal output into the legacy
            # strategies-dict shape that _parse_quant_result expects.
            component_signals = result.get("component_signals", {})
            strategies: Dict[str, Dict] = {}
            for key, value in component_signals.items():
                if isinstance(value, dict):
                    strategies[key] = value
                else:
                    strategies[key] = {"score": float(value), "confidence": 0.6}

            strategies.setdefault("regime", {}).update(
                {"score": 0, "regime": result.get("regime", "unknown")}
            )

            return {
                "symbol": result.get("symbol", symbol),
                "strategies": strategies,
                "trigger_reason": result.get("trigger_reason", "automated_analysis"),
            }

        except asyncio.TimeoutError:
            self.logger.warning(f"Quant toolkit timeout for {symbol}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to call quant toolkit: {e}", exc_info=True)
            return None

    def _parse_quant_result(self, symbol: str, result: Dict) -> Dict:
        """Parse quant toolkit result into signal format."""
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

        all_scores = [
            momentum_conf,
            reversion_conf,
            pattern.get("confidence", 0),
            regime.get("confidence", 0),
            correlation.get("confidence", 0),
            leading.get("confidence", 0),
        ]
        aggregate_confidence = sum(all_scores) / len(all_scores) if all_scores else 0.5

        signal_type = self._determine_signal_type(
            momentum_score, reversion_score, pattern_score, regime_score
        )

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
            "trigger_reason": str(result.get("trigger_reason", "automated_analysis")),
        }

    def _determine_signal_type(
        self, momentum: float, reversion: float, pattern: float, regime: float
    ) -> str:
        weighted_score = (
            momentum * 0.4 + pattern * 0.25 + regime * 0.2 + reversion * 0.15
        )
        if weighted_score > 0.3:
            return "buy"
        elif weighted_score < -0.3:
            return "sell"
        return "neutral"

    def _neutral_signal(self, symbol: str) -> Dict:
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
            "trigger_reason": "error_or_no_signal",
        }

    async def get_regime_state(self, prices: Optional[List[float]] = None) -> Dict:
        """
        Compute current market regime using QuantToolkit.market_regime.

        Args:
            prices: Optional list of close prices (e.g. SPY's recent history).
                    If None, returns cached value or default regime — we do
                    NOT fabricate synthetic data.
        """
        now = datetime.utcnow()
        if (
            self.regime_cache
            and self.regime_cache_time
            and (now - self.regime_cache_time).total_seconds() < self.regime_cache_ttl
        ):
            return self.regime_cache

        self._load_toolkit()
        if not self._toolkit:
            return self._default_regime()

        # No real prices supplied → don't make up data; return default.
        if not prices or len(prices) < 60:
            return self._default_regime()

        try:
            prices_array = np.array(prices, dtype=float)
            loop = asyncio.get_event_loop()
            toolkit_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._toolkit.market_regime, prices_array
                ),
                timeout=10,
            )

            # Map toolkit's schema → main.py's expected RegimeState fields.
            result = self._map_regime(toolkit_result)
            self.regime_cache = result
            self.regime_cache_time = now
            return result

        except Exception as e:
            self.logger.warning(f"Failed to get regime state: {e}")
            return self._default_regime()

    def _map_regime(self, toolkit_result: Dict) -> Dict:
        """Translate quant-toolkit regime output to RegimeState fields."""
        regime = toolkit_result.get("regime", "neutral")
        confidence = toolkit_result.get("confidence", 50) / 100.0
        avg_return = toolkit_result.get("avg_daily_return", 0.0)
        volatility = toolkit_result.get("volatility", 0.0)

        # hmm_phase: 0=bear, 1=neutral, 2=bull
        if regime.startswith("bull"):
            hmm_phase = 2
            trend = "bullish"
        elif regime.startswith("bear"):
            hmm_phase = 0
            trend = "bearish"
        else:
            hmm_phase = 1
            trend = "neutral"

        if volatility > 0.020:
            vol_regime = "high"
        elif volatility < 0.010:
            vol_regime = "low"
        else:
            vol_regime = "normal"

        # market_heat: normalized abs(return) heat metric in [0, 1]
        market_heat = float(min(1.0, abs(avg_return) * 100 + volatility * 10))

        return {
            "hmm_phase": hmm_phase,
            "volatility_regime": vol_regime,
            "market_heat": market_heat,
            "trend_direction": trend,
            "estimated_probability": float(confidence),
            "raw_regime": regime,
        }

    def _default_regime(self) -> Dict:
        return {
            "hmm_phase": 1,
            "volatility_regime": "normal",
            "market_heat": 0.5,
            "trend_direction": "neutral",
            "estimated_probability": 0.33,
        }
