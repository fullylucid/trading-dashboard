#!/usr/bin/env python3
"""Shared technical indicators for Charlotte detectors.
Pure numpy/pandas, no LLM, no network. All functions accept arrays and
return floats or arrays; None is returned when there isn't enough data.
"""
import numpy as np
import pandas as pd


def rsi(closes, period=14):
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g = float(np.mean(gains[:period]))
    avg_l = float(np.mean(losses[:period]))
    for i in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def rsi_series(closes, period=14):
    """Full RSI series aligned to closes (NaNs prefix)."""
    s = pd.Series(closes, dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50).values


def macd_hist(closes, fast=12, slow=26, sig=9):
    if len(closes) < slow + sig:
        return None, None
    s = pd.Series(closes, dtype=float)
    ema_f = s.ewm(span=fast, adjust=False).mean().values
    ema_s = s.ewm(span=slow, adjust=False).mean().values
    macd = ema_f - ema_s
    signal = pd.Series(macd).ewm(span=sig, adjust=False).mean().values
    hist = macd - signal
    return float(hist[-1]), float(hist[-2])


def adx(highs, lows, closes, period=14):
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    if n < period * 2 + 1:
        return None
    up = highs[1:] - highs[:-1]
    dn = lows[:-1] - lows[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - closes[:-1]),
        np.abs(lows[1:] - closes[:-1]),
    ])
    atr = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean().values
    pdi = 100 * pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean().values / np.where(atr == 0, np.nan, atr)
    ndi = 100 * pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean().values / np.where(atr == 0, np.nan, atr)
    dx = 100 * np.abs(pdi - ndi) / np.where((pdi + ndi) == 0, np.nan, pdi + ndi)
    adx_val = pd.Series(dx).ewm(alpha=1/period, adjust=False).mean().values
    v = adx_val[-1]
    return None if np.isnan(v) else float(v)


def atr(highs, lows, closes, period=14):
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return None
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - closes[:-1]),
        np.abs(lows[1:] - closes[:-1]),
    ])
    return float(pd.Series(tr).ewm(alpha=1/period, adjust=False).mean().iloc[-1])


def sma(closes, window):
    closes = np.asarray(closes, dtype=float)
    if len(closes) < window:
        return None
    return float(np.mean(closes[-window:]))


def sma_slope(closes, window=200, lookback=20):
    """Slope (per-bar) of the trailing SMA over the last `lookback` bars."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < window + lookback:
        return None
    s = pd.Series(closes).rolling(window).mean().values
    seg = s[-lookback:]
    if np.isnan(seg).any():
        return None
    x = np.arange(lookback)
    slope = np.polyfit(x, seg, 1)[0]
    return float(slope)


def bearish_rsi_divergence(closes, rsis, lookback=20):
    if len(closes) < lookback + 2:
        return False
    cs = closes[-lookback:]
    rs = rsis[-lookback:]
    mid = lookback // 2
    p1 = float(np.max(cs[:mid])); p2 = float(np.max(cs[mid:]))
    r1 = float(np.max(rs[:mid])); r2 = float(np.max(rs[mid:]))
    return p2 > p1 and r2 < r1


def bullish_rsi_divergence(closes, rsis, lookback=20):
    if len(closes) < lookback + 2:
        return False
    cs = closes[-lookback:]
    rs = rsis[-lookback:]
    mid = lookback // 2
    p1 = float(np.min(cs[:mid])); p2 = float(np.min(cs[mid:]))
    r1 = float(np.min(rs[:mid])); r2 = float(np.min(rs[mid:]))
    return p2 < p1 and r2 > r1
