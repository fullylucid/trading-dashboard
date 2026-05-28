#!/usr/bin/env python3
"""Multi-factor scorer for Charlotte signals.
Combines 4 pillars -> 0..10. Pure Python, no LLM.
Pillars: Technical 0-3, Fundamental 0-2.5, Quant/Risk 0-2, Sentiment 0-2.5.
"""
import sys

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte import data_fetch as df_mod


def _technical(s):
    """s: dict with technical features from detector."""
    pts = 0.0
    rsi = s.get('rsi')
    if rsi is not None:
        if rsi >= 80 or rsi <= 20: pts += 1.0
        elif rsi >= 75 or rsi <= 25: pts += 0.75
        elif rsi >= 70 or rsi <= 30: pts += 0.5
    if s.get('macd_cross'): pts += 0.7
    adx = s.get('adx')
    if adx is not None and adx >= 25: pts += 0.6
    if s.get('mtf_confirm'): pts += 0.4
    if s.get('divergence'): pts += 0.3
    return min(3.0, pts)


def _fundamental(symbol, side='peak'):
    info = df_mod.fetch_info(symbol)
    pts = 0.0
    pe = info.get('forwardPE') or info.get('trailingPE')
    if pe and pe > 0:
        if side == 'peak' and pe > 40: pts += 0.8
        elif side == 'peak' and pe > 25: pts += 0.4
        elif side == 'trough' and pe < 15: pts += 0.8
        elif side == 'trough' and pe < 20: pts += 0.4
    revs = df_mod.fetch_quarterly_revenue(symbol)
    if len(revs) >= 6:
        recent_yoy = (revs[0] - revs[4]) / abs(revs[4]) if revs[4] else 0
        prior_yoy = (revs[1] - revs[5]) / abs(revs[5]) if revs[5] else 0
        if side == 'peak' and recent_yoy < prior_yoy: pts += 0.8
        elif side == 'trough' and recent_yoy > prior_yoy: pts += 0.8
        else: pts += 0.3
    op_margin = info.get('operatingMargins')
    if op_margin is not None:
        if side == 'peak' and op_margin < 0.05: pts += 0.5
        elif side == 'trough' and op_margin > 0.10: pts += 0.5
        else: pts += 0.2
    return min(2.5, pts)


def _quant_risk(s):
    pts = 0.0
    atr_pct = s.get('atr_pct')
    if atr_pct is not None:
        if atr_pct < 4: pts += 1.0
        elif atr_pct < 7: pts += 0.6
        else: pts += 0.2
    n_signals = len(s.get('reasons', []))
    pts += min(1.0, n_signals * 0.25)
    return min(2.0, pts)


def _sentiment(symbol, side='peak'):
    ups, downs = df_mod.fetch_recommendations(symbol, days=90)
    pol = df_mod.fetch_news_polarity(symbol)
    pts = 0.0
    if side == 'peak':
        if downs > ups: pts += 1.3
        elif downs == ups and downs > 0: pts += 0.5
        if pol < 0: pts += min(1.2, abs(pol) * 0.3)
    elif side == 'trough':
        # contrarian: heavy downgrades + bad news = buy signal
        if downs > ups: pts += 1.0
        if pol < -1: pts += min(1.5, abs(pol) * 0.35)
    else:  # secular_top - confirming
        if downs > ups: pts += 1.5
        if pol < 0: pts += min(1.0, abs(pol) * 0.25)
    return min(2.5, pts)


def score(symbol, signals, side='peak', pillars_hit=0):
    """signals: dict produced by a detector. side: peak|trough|secular_top.
    pillars_hit: count of 4 pillars firing; +1.5 per pillar beyond 2, capped at 10."""
    t = _technical(signals)
    try:
        f = _fundamental(symbol, 'trough' if side == 'trough' else 'peak')
    except (ValueError, KeyError, AttributeError):
        f = 0
    q = _quant_risk(signals)
    try:
        sent = _sentiment(symbol, side)
    except (ValueError, KeyError, AttributeError):
        sent = 0
    total = t + f + q + sent
    pillar_bonus = max(0, int(pillars_hit) - 2) * 1.75  # v3.2: 1.5->1.75 lifts 3-pillar fires above 6.0 floor
    final = min(10.0, total + pillar_bonus)
    return round(final, 2), {'technical': round(t, 2), 'fundamental': round(f, 2),
                              'quant': round(q, 2), 'sentiment': round(sent, 2),
                              'pillar_bonus': round(pillar_bonus, 2),
                              'pillars_hit': int(pillars_hit)}
