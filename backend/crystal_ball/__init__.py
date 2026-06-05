"""
Crystal Ball — the dark art of prediction.

A calibrated reversal-probability engine. It does NOT claim to call exact tops
and bottoms with certainty (nobody can — markets are non-stationary and partly
reflexive). Instead it fuses physics-of-markets math (Hurst, Ornstein-Uhlenbeck
mean reversion, permutation entropy) with classic reversal triggers (RSI/MACD
divergence, Bollinger extension, exhaustion) into a single honest read:

    "X% chance a local reversal (top/bottom) is near, confidence <level>,
     here's why, and here's what kills the thesis."

Honesty is a first-class feature: permutation entropy gates confidence — when a
regime is statistically unpredictable, the engine says so and caps its own
confidence rather than projecting false certainty.

Pure numpy/scipy; reuses the tested ``analytics.signals`` package for the
classic indicators and ``scan_analytics`` for the (no-look-ahead) candle feed.
"""

from .fusion import crystal_ball_read  # noqa: F401

__all__ = ["crystal_ball_read"]
