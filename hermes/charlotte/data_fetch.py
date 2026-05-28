#!/usr/bin/env python3
"""Yfinance data fetch helpers with graceful fallback.
Single 1y OHLCV pull + optional fundamentals/news. Cached per process."""
import sys
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf

_CACHE = {}


def fetch_ohlcv(symbol, days=420):
    key = (symbol, days)
    if key in _CACHE:
        return _CACHE[key]
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=False)
    except (ValueError, KeyError, ConnectionError) as e:
        print(f"[{symbol}] download error: {e}", file=sys.stderr)
        _CACHE[key] = None
        return None
    if df is None or df.empty or len(df) < 30:
        _CACHE[key] = None
        return None
    if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
        df.columns = df.columns.droplevel(1)
    _CACHE[key] = df
    return df


def spy_bull_regime():
    """True iff SPY close > 200SMA AND 200SMA slope over last 20 bars > 0.

    Cached per process via fetch_ohlcv cache. Returns (bool, dict) for logging.
    """
    key = ('spy_bull_regime',)
    if key in _CACHE:
        return _CACHE[key]
    df = fetch_ohlcv('SPY', days=420)
    if df is None or len(df) < 220:
        _CACHE[key] = (False, {'reason': 'insufficient data'})
        return _CACHE[key]
    closes = df['Close'].values.flatten()
    sma200 = pd.Series(closes).rolling(200).mean().values
    if np.isnan(sma200[-1]) or np.isnan(sma200[-20]):
        _CACHE[key] = (False, {'reason': 'sma200 NaN'})
        return _CACHE[key]
    slope = float(np.polyfit(np.arange(20), sma200[-20:], 1)[0])
    bull = bool(closes[-1] > sma200[-1] and slope > 0)
    info = {'spy_close': float(closes[-1]), 'sma200': float(sma200[-1]),
            'slope20': slope, 'bull': bull}
    _CACHE[key] = (bull, info)
    return _CACHE[key]


def fetch_weekly_rsi_series(symbol):
    df = fetch_ohlcv(symbol)
    if df is None:
        return None
    weekly = df['Close'].resample('W').last().dropna().values
    if len(weekly) < 20:
        return None
    return weekly


def fetch_info(symbol):
    key = ('info', symbol)
    if key in _CACHE:
        return _CACHE[key]
    info = {}
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
    except (ValueError, KeyError, ConnectionError, AttributeError) as e:
        print(f"[{symbol}] info error: {e}", file=sys.stderr)
    _CACHE[key] = info
    return info


def fetch_quarterly_revenue(symbol):
    """Return list of last 8 quarterly revenue (Total Revenue) newest->oldest."""
    try:
        t = yf.Ticker(symbol)
        qf = t.quarterly_financials
        if qf is None or qf.empty:
            return []
        for label in ('Total Revenue', 'TotalRevenue', 'Revenue'):
            if label in qf.index:
                return [float(x) for x in qf.loc[label].values if not pd.isna(x)]
    except (ValueError, KeyError, AttributeError, ConnectionError) as e:
        print(f"[{symbol}] quarterly revenue error: {e}", file=sys.stderr)
    return []


def fetch_recommendations(symbol, days=90):
    """Net upgrades-downgrades in last N days. Returns (upgrades, downgrades)."""
    try:
        t = yf.Ticker(symbol)
        rec = t.recommendations
        if rec is None or rec.empty:
            return 0, 0
        cutoff = datetime.now() - timedelta(days=days)
        if hasattr(rec.index, 'tz'):
            rec.index = rec.index.tz_localize(None) if rec.index.tz else rec.index
        rec = rec[rec.index >= cutoff] if hasattr(rec.index, 'dtype') and 'datetime' in str(rec.index.dtype).lower() else rec.tail(20)
        col = None
        for c in rec.columns:
            if 'grade' in c.lower() and 'to' in c.lower():
                col = c; break
        if col is None and 'To Grade' in rec.columns:
            col = 'To Grade'
        ups = downs = 0
        if col and 'From Grade' in rec.columns:
            up_kw = {'buy', 'outperform', 'overweight', 'strong buy', 'accumulate'}
            dn_kw = {'sell', 'underperform', 'underweight', 'strong sell', 'reduce'}
            for _, row in rec.iterrows():
                tg = str(row.get(col, '')).lower()
                fg = str(row.get('From Grade', '')).lower()
                if any(k in tg for k in up_kw) and not any(k in fg for k in up_kw):
                    ups += 1
                if any(k in tg for k in dn_kw):
                    downs += 1
        elif 'strongBuy' in rec.columns or 'buy' in rec.columns:
            ups = int(rec.get('strongBuy', pd.Series([0])).sum() + rec.get('buy', pd.Series([0])).sum())
            downs = int(rec.get('sell', pd.Series([0])).sum() + rec.get('strongSell', pd.Series([0])).sum())
        return ups, downs
    except (ValueError, KeyError, AttributeError, ConnectionError) as e:
        print(f"[{symbol}] recs error: {e}", file=sys.stderr)
        return 0, 0


def fetch_news_polarity(symbol):
    """+1 per bullish keyword, -1 per bearish in recent news titles. Clamped [-5,5]."""
    bullish = {'beat', 'beats', 'surge', 'rally', 'upgrade', 'strong', 'record', 'soar', 'jump', 'boost', 'breakthrough'}
    bearish = {'miss', 'misses', 'plunge', 'cut', 'downgrade', 'weak', 'lawsuit', 'probe', 'sink', 'slump', 'warning', 'fraud'}
    try:
        t = yf.Ticker(symbol)
        news = t.news or []
    except (ValueError, KeyError, AttributeError, ConnectionError):
        return 0
    score = 0
    for n in news[:15]:
        title = (n.get('title') or n.get('content', {}).get('title') or '').lower()
        for w in bullish:
            if w in title: score += 1
        for w in bearish:
            if w in title: score -= 1
    return max(-5, min(5, score))
