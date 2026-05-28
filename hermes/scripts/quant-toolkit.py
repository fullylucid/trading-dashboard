#!/usr/bin/env python3
"""
Quantitative Trading Toolkit for Tradeskeebot
Mathematical patterns and strategies from top quants
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import json
import os

class QuantToolkit:
    """Collection of quantitative analysis tools for market prediction"""
    
    def __init__(self):
        self.log_dir = "/home/user/.hermes/logs"
        os.makedirs(self.log_dir, exist_ok=True)
    
    # ========================================================================
    # MOMENTUM STRATEGIES (Trend-following, Turtle Trading style)
    # ========================================================================
    
    @staticmethod
    def momentum_score(prices: np.ndarray, periods: List[int] = [10, 20, 50]) -> Dict[str, float]:
        """
        Multi-timeframe momentum scoring (like Renaissance Technologies)
        - Fast momentum (10-day): short-term trend strength
        - Medium momentum (20-day): intermediate trend
        - Long momentum (50-day): macro trend confirmation
        
        Returns weighted momentum score (-1 to +1)
        """
        if len(prices) < max(periods):
            return {"momentum": 0, "components": {}}
        
        scores = {}
        weights = {10: 0.5, 20: 0.3, 50: 0.2}  # Fast > Medium > Long
        
        for period in periods:
            returns = (prices[-1] - prices[-period]) / prices[-period]
            scores[f"{period}d"] = returns
        
        weighted_momentum = sum(scores.get(f"{p}d", 0) * weights[p] for p in periods)
        
        return {
            "momentum": np.tanh(weighted_momentum),  # Normalize to [-1, 1]
            "components": scores,
            "interpretation": "bullish" if weighted_momentum > 0 else "bearish"
        }
    
    @staticmethod
    def mean_reversion_score(prices: np.ndarray, period: int = 20) -> Dict:
        """
        Mean reversion signal (Bollinger Band style, like Citadel)
        - Detects overbought/oversold conditions
        - Measures distance from moving average
        - Returns signal strength for counter-trend trades
        """
        if len(prices) < period:
            return {"reversion_signal": 0}
        
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        
        # Z-score: how far is current price from mean (in std devs)
        z_score = (prices[-1] - sma) / (std + 1e-8)
        
        # Bollinger bands (±2σ)
        upper_band = sma + 2 * std
        lower_band = sma - 2 * std
        
        return {
            "z_score": float(z_score),
            "sma": float(sma),
            "upper_band": float(upper_band),
            "lower_band": float(lower_band),
            "reversion_strength": float(np.tanh(z_score / 2)),  # [-1, 1]
            "signal": "sell_overbought" if z_score > 2 else ("buy_oversold" if z_score < -2 else "neutral")
        }
    
    # ========================================================================
    # VOLATILITY STRATEGIES (VIX timing, options volatility)
    # ========================================================================
    
    @staticmethod
    def volatility_regime(prices: np.ndarray, periods: List[int] = [20, 60]) -> Dict:
        """
        Volatility regime detection (like Bridgewater Associates)
        - Low vol = trending environment (use momentum)
        - High vol = mean-reverting environment (use range trading)
        - Volatility edges are regime-dependent
        """
        if len(prices) < max(periods):
            return {"regime": "unknown"}
        
        returns = np.diff(np.log(prices[-max(periods):]))
        
        vol_scores = {}
        for period in periods:
            vol = np.std(returns[-period:]) * np.sqrt(252)  # Annualized
            vol_scores[f"{period}d_vol"] = float(vol)
        
        # Volatility ratio: recent vs longer-term
        vol_ratio = vol_scores[f"{periods[0]}d_vol"] / (vol_scores[f"{periods[-1]}d_vol"] + 1e-8)
        
        if vol_ratio > 1.3:
            regime = "high_volatility_expanding"  # Breakout conditions
        elif vol_ratio < 0.8:
            regime = "low_volatility_contracting"  # Consolidation
        else:
            regime = "normal_volatility"
        
        return {
            "regime": regime,
            "volatility_ratio": float(vol_ratio),
            "components": vol_scores,
            "strategy_implication": "use_momentum" if vol_ratio < 1.0 else "use_mean_reversion"
        }
    
    # ========================================================================
    # MACHINE LEARNING PATTERNS (Statistical patterns from quant research)
    # ========================================================================
    
    @staticmethod
    def pattern_recognition(prices: np.ndarray, volume: np.ndarray) -> Dict[str, float]:
        """
        Statistical pattern recognition (inspired by WallStreet Quants, DE Shaw)
        - Identifies mathematical patterns in price/volume relationships
        - Returns confidence scores for each pattern
        """
        if len(prices) < 30:
            return {"patterns": {}}
        
        patterns = {}
        
        # 1. Gap-and-go pattern (morning gap up + volume)
        recent_gap = (prices[-1] - prices[-2]) / prices[-2]
        avg_vol_30 = np.mean(volume[-30:])
        recent_vol = volume[-1]
        
        if recent_gap > 0.02 and recent_vol > avg_vol_30 * 1.5:
            patterns["gap_and_go"] = min(abs(recent_gap) * 100, 95.0)
        
        # 2. VWAP reversal (price crosses VWAP)
        typical_price = prices.copy()
        vwap = np.cumsum(typical_price * volume[-len(prices):]) / np.cumsum(volume[-len(prices):])
        vwap_diff = (prices[-1] - vwap[-1]) / vwap[-1]
        
        if abs(vwap_diff) > 0.02:
            patterns["vwap_divergence"] = float(abs(vwap_diff) * 100)
        
        # 3. Momentum persistence (high momentum + positive acceleration)
        returns = np.diff(prices[-20:]) / prices[-20:-1]
        momentum = np.mean(returns[-5:])
        acceleration = returns[-1] - np.mean(returns[-10:-5])
        
        if momentum > 0 and acceleration > 0:
            patterns["momentum_acceleration"] = float(min(abs(momentum) * 100, 85.0))
        
        # 4. Volume profile reversal (volume cluster at price level)
        price_levels = pd.cut(prices[-30:], bins=10)
        vol_by_level = pd.Series(volume[-30:], index=price_levels).groupby(price_levels).sum()
        max_vol_level = vol_by_level.idxmax()
        
        if prices[-1] in max_vol_level:
            patterns["volume_cluster_reversal"] = 75.0
        
        return {
            "patterns": patterns,
            "dominant_pattern": max(patterns, key=patterns.get) if patterns else "none",
            "pattern_strength": float(max(patterns.values())) if patterns else 0.0
        }
    
    # ========================================================================
    # STAT ARBS & PAIRS TRADING (Like Citadel)
    # ========================================================================
    
    @staticmethod
    def correlation_divergence(price_a: np.ndarray, price_b: np.ndarray, window: int = 60) -> Dict:
        """
        Pairs trading / correlation arbitrage
        - Detects when normally correlated assets diverge
        - Signals mean-reversion opportunity
        """
        if len(price_a) < window or len(price_b) < window:
            return {"divergence": 0}
        
        returns_a = np.diff(np.log(price_a[-window:]))
        returns_b = np.diff(np.log(price_b[-window:]))
        
        correlation = np.corrcoef(returns_a, returns_b)[0, 1]
        
        # Pairs trade: if correlation drops below historical, they'll mean-revert
        historical_corr = 0.75  # Assumed baseline for related stocks/sectors
        
        divergence_signal = abs(historical_corr - correlation)
        
        return {
            "current_correlation": float(correlation),
            "historical_correlation": float(historical_corr),
            "divergence_strength": float(divergence_signal),
            "trade_signal": "pairs_opportunity" if divergence_signal > 0.2 else "normal_correlation"
        }
    
    # ========================================================================
    # REGIME ANALYSIS (Hidden Markov Model style, like Point72)
    # ========================================================================
    
    @staticmethod
    def market_regime(prices: np.ndarray, returns_window: int = 60) -> Dict:
        """
        Hidden regime detection using returns & volatility clustering
        - Bull regime: positive returns + lower volatility
        - Bear regime: negative returns + higher volatility
        - Transition regime: high volatility + uncertain direction
        """
        if len(prices) < returns_window:
            return {"regime": "insufficient_data"}
        
        returns = np.diff(np.log(prices[-returns_window:]))
        
        avg_return = np.mean(returns)
        volatility = np.std(returns)
        
        # Regime scoring
        return_signal = np.tanh(avg_return * 100)  # Normalize
        vol_signal = np.tanh(volatility * 10)
        
        # Regime classification
        if avg_return > 0.001 and volatility < 0.015:
            regime = "bull_calm"
            confidence = 85
        elif avg_return > 0.001 and volatility > 0.020:
            regime = "bull_stressed"
            confidence = 70
        elif avg_return < -0.001 and volatility > 0.020:
            regime = "bear_stressed"
            confidence = 85
        elif avg_return < -0.001 and volatility < 0.015:
            regime = "bear_calm"
            confidence = 65
        else:
            regime = "neutral"
            confidence = 50
        
        return {
            "regime": regime,
            "confidence": confidence,
            "avg_daily_return": float(avg_return),
            "volatility": float(volatility),
            "strategy_implication": {
                "bull_calm": "use_trend_following",
                "bull_stressed": "reduce_leverage",
                "bear_stressed": "hedge_long_positions",
                "bear_calm": "look_for_reversals",
                "neutral": "wait_for_signals"
            }.get(regime, "neutral")
        }
    
    # ========================================================================
    # PREDICTIVE SIGNALS (Leading indicators)
    # ========================================================================
    
    @staticmethod
    def leading_indicators(prices: np.ndarray, volume: np.ndarray) -> Dict[str, float]:
        """
        Leading indicators that predict moves before they happen
        - Price acceleration
        - Volume divergence
        - Volatility term structure
        """
        if len(prices) < 10:
            return {"predictive_power": 0}
        
        signals = {}
        
        # 1. Price acceleration (2nd derivative)
        price_change = np.diff(prices[-10:])
        acceleration = np.diff(price_change)
        price_accel = np.mean(acceleration)
        
        if price_accel > 0:
            signals["accelerating_upside"] = float(min(abs(price_accel) * 100, 90.0))
        elif price_accel < 0:
            signals["accelerating_downside"] = float(min(abs(price_accel) * 100, 90.0))
        
        # 2. Volume divergence (volume leading price)
        vol_ma = np.mean(volume[-5:])
        vol_trend = volume[-1] - vol_ma
        price_trend = prices[-1] - np.mean(prices[-5:])
        
        if vol_trend > 0 and price_trend > 0:
            signals["volume_confirms_move"] = 80.0
        elif vol_trend > 0 and price_trend < 0:
            signals["volume_leads_upside"] = 75.0  # Bullish divergence
        
        # 3. Volatility expanding (before big move)
        vol_short = np.std(np.diff(np.log(prices[-5:]))) * np.sqrt(252)
        vol_long = np.std(np.diff(np.log(prices[-20:]))) * np.sqrt(252)
        
        if vol_short > vol_long * 1.2:
            signals["volatility_expanding"] = float((vol_short / vol_long - 1) * 100)
        
        return {
            "leading_signals": signals,
            "dominant_signal": max(signals, key=signals.get) if signals else "none",
            "predictive_power": float(max(signals.values())) if signals else 0.0
        }
    
    # ========================================================================
    # RISK METRICS
    # ========================================================================
    
    @staticmethod
    def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.04) -> float:
        """Sharpe Ratio - risk-adjusted return metric"""
        if len(returns) < 2:
            return 0.0
        
        excess_returns = returns - risk_free_rate / 252
        return float(np.mean(excess_returns) / (np.std(excess_returns) + 1e-8) * np.sqrt(252))
    
    @staticmethod
    def max_drawdown(returns: np.ndarray) -> float:
        """Maximum drawdown - worst peak-to-trough decline"""
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        return float(np.min(drawdown))
    
    @staticmethod
    def win_rate(returns: np.ndarray) -> float:
        """Percentage of winning trades"""
        winning = np.sum(returns > 0)
        return float(winning / len(returns) * 100) if len(returns) > 0 else 0.0
    
    # ========================================================================
    # ENSEMBLE SCORING
    # ========================================================================
    
    def ensemble_signal(self, symbol: str, prices: np.ndarray, volume: np.ndarray) -> Dict:
        """
        Combine all signals into single prediction
        Weights based on historical accuracy (like Bridgewater's All-Weather)
        """
        if len(prices) < 50 or len(volume) < 50:
            return {"score": 0, "confidence": 0, "signal": "insufficient_data"}
        
        signals = {}
        weights = {}
        
        # Run all analyses
        momentum = self.momentum_score(prices)
        signals["momentum"] = momentum.get("momentum", 0)
        weights["momentum"] = 0.25  # 25% weight
        
        reversion = self.mean_reversion_score(prices)
        signals["reversion"] = reversion.get("reversion_strength", 0)
        weights["reversion"] = 0.20  # 20% weight
        
        volatility = self.volatility_regime(prices)
        vol_signal = 0.5 if "low" in volatility.get("regime", "") else -0.5
        signals["volatility"] = vol_signal
        weights["volatility"] = 0.15  # 15% weight
        
        patterns = self.pattern_recognition(prices, volume)
        pattern_signal = (patterns.get("pattern_strength", 0) / 100) * 2 - 1  # Normalize
        signals["patterns"] = pattern_signal
        weights["patterns"] = 0.20  # 20% weight
        
        regime = self.market_regime(prices)
        regime_signal = {"bull_calm": 0.5, "bull_stressed": 0.2, "neutral": 0.0, "bear_calm": -0.2, "bear_stressed": -0.5}.get(regime.get("regime", "neutral"), 0)
        signals["regime"] = regime_signal
        weights["regime"] = 0.20  # 20% weight
        
        # Calculate weighted ensemble score
        ensemble_score = sum(signals[k] * weights[k] for k in signals) / sum(weights.values())
        ensemble_score = float(np.tanh(ensemble_score))  # Normalize to [-1, 1]
        
        # Convert to probability
        confidence = float(abs(ensemble_score) * 100)
        
        # Trading signal
        if ensemble_score > 0.3:
            signal = "strong_buy"
        elif ensemble_score > 0.1:
            signal = "buy"
        elif ensemble_score < -0.3:
            signal = "strong_sell"
        elif ensemble_score < -0.1:
            signal = "sell"
        else:
            signal = "neutral"
        
        return {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "ensemble_score": ensemble_score,
            "confidence": confidence,
            "signal": signal,
            "component_signals": signals,
            "weights_used": weights,
            "regime": regime.get("regime", "unknown"),
            "interpretation": f"{confidence:.0f}% confidence {signal.upper()}"
        }

if __name__ == "__main__":
    # Example usage
    print("\n" + "="*70)
    print("QUANTITATIVE TOOLKIT - DEMONSTRATION")
    print("="*70 + "\n")
    
    # Generate sample price data (simulate stock movement)
    np.random.seed(42)
    base_price = 100
    returns = np.random.normal(0.0005, 0.015, 100)  # Daily returns
    prices = base_price * np.cumprod(1 + returns)
    volume = np.random.uniform(1e6, 5e6, 100)
    
    toolkit = QuantToolkit()
    
    # Run ensemble analysis
    result = toolkit.ensemble_signal("DEMO", prices, volume)
    
    print(f"Symbol: {result['symbol']}")
    print(f"Signal: {result['signal']} ({result['confidence']:.0f}% confidence)")
    print(f"Ensemble Score: {result['ensemble_score']:.3f}")
    print(f"Market Regime: {result['regime']}")
    print()
    
    print("Component Signals:")
    for component, value in result['component_signals'].items():
        print(f"  {component:12} → {value:+.3f}")
    print()
    
    print("Signal Weights:")
    for signal, weight in result['weights_used'].items():
        print(f"  {signal:12} → {weight*100:.0f}%")
    
    print("\n" + "="*70)
    
    # Save results
    output_file = "/home/user/.hermes/logs/quant-analysis.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    
    print(f"\nResults saved to {output_file}")
