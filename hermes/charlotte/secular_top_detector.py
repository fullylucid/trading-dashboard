#!/usr/bin/env python3
"""Charlotte Secular Top Detector v2.

Thirteen signals across four pillars (technical / fundamental / quant /
sentiment). HIGH-confidence fire requires >=3 signals across >=2 pillars.
Pillars-hit >= 3 -> trim 75% + full thesis review.
Else                trim 50% + thesis review.

Public API preserved:
    detect(symbols: list) -> list[dict]
    CLI:  python -m charlotte.secular_top_detector --symbol AAPL [--force]
          python -m charlotte.secular_top_detector AAPL MSFT ...   (positional)
"""
from __future__ import annotations
import sys
import json
import argparse
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte import indicators as ind
from charlotte import data_fetch as df_mod
from charlotte import multi_factor_scorer as scorer


# ----------------------------- TECHNICAL ----------------------------- #

def _sig_close_below_sma200(closes):
    if len(closes) < 203:
        return False, None
    s = pd.Series(closes).rolling(200).mean().values
    if np.isnan(s[-3]):
        return False, None
    return bool(np.all(closes[-3:] < s[-3:])), "3d close<200SMA"


def _sig_sma200_slope_neg(closes):
    slope = ind.sma_slope(closes, 200, 20)
    if slope is None:
        return False, None
    return slope < 0, f"200SMA slope {slope:.3f}"


def _sig_death_cross(closes, lookback=30):
    if len(closes) < 210:
        return False, None
    s50 = pd.Series(closes).rolling(50).mean().values
    s200 = pd.Series(closes).rolling(200).mean().values
    seg50 = s50[-lookback - 1:]
    seg200 = s200[-lookback - 1:]
    if np.isnan(seg50).any() or np.isnan(seg200).any():
        return False, None
    diff = seg50 - seg200
    crossed = np.any((diff[:-1] > 0) & (diff[1:] <= 0))
    return bool(crossed), "death cross <30d"


def _sig_weekly_lower_highs(closes_index, closes):
    if len(closes) < 120:
        return False, None
    try:
        s = pd.Series(closes, index=closes_index)
        weekly = s.resample('W').max().dropna()
    except (TypeError, ValueError):
        return False, None
    if len(weekly) < 12:
        return False, None
    # local maxima: weekly[i] > neighbours
    w = weekly.values
    peaks = [i for i in range(1, len(w) - 1) if w[i] > w[i - 1] and w[i] > w[i + 1]]
    if len(peaks) < 3:
        return False, None
    last3 = [w[i] for i in peaks[-3:]]
    return last3[0] > last3[1] > last3[2], "weekly LH x3"


def _sig_distribution_top(closes):
    if len(closes) < 250:
        return False, None
    # Find the 2 highest local peaks separated by >=60 bars, within 5% of each other,
    # and current price is within 5% of that level (distribution / double-top zone).
    s = pd.Series(closes)
    # rolling max window 10 to find local peaks
    peaks = []
    for i in range(20, len(closes) - 20):
        if closes[i] == max(closes[i - 20:i + 21]):
            peaks.append((i, closes[i]))
    if len(peaks) < 2:
        return False, None
    peaks.sort(key=lambda x: -x[1])
    top1 = peaks[0]
    candidates = [p for p in peaks[1:] if abs(p[0] - top1[0]) >= 60 and abs(p[1] - top1[1]) / top1[1] < 0.05]
    if not candidates:
        return False, None
    level = (top1[1] + candidates[0][1]) / 2
    if abs(closes[-1] - level) / level < 0.05:
        return True, f"dist-top ~{level:.0f}"
    return False, None


# ----------------------------- FUNDAMENTAL --------------------------- #

def _sig_pe_extreme(info):
    pe = info.get('trailingPE') or info.get('forwardPE')
    if not pe or pe <= 0:
        return False, None
    # No 5yr median available without history calls; use absolute 40 as fallback
    if pe > 40:
        return True, f"P/E {pe:.0f} extreme"
    return False, None


def _sig_ev_ebitda(info):
    ev = info.get('enterpriseToEbitda')
    if ev is None or ev <= 0:
        return False, None
    if ev > 25:
        return True, f"EV/EBITDA {ev:.0f}"
    return False, None


def _sig_rev_decel(revs):
    if len(revs) < 7:
        return False, None
    yoys = []
    for i in range(3):
        if revs[i + 4]:
            yoys.append((revs[i] - revs[i + 4]) / abs(revs[i + 4]))
    if len(yoys) < 3:
        return False, None
    # yoys[0] = most recent quarter; declining means each newer < older
    if yoys[0] < yoys[1] < yoys[2]:
        return True, "Rev YoY decel 3Q"
    return False, None


def _sig_negative_revisions(ups, downs):
    if downs > ups and downs >= 2:
        return True, f"downgrades {downs}>{ups}"
    return False, None


# ----------------------------- QUANT --------------------------------- #

def _sig_stretched_above_sma(closes):
    s200 = ind.sma(closes, 200)
    if s200 is None or s200 <= 0:
        return False, None
    stretch = closes[-1] / s200 - 1
    if stretch > 0.30:
        return True, f"+{stretch*100:.0f}% over 200SMA"
    return False, None


def _sig_high_atr(highs, lows, closes):
    a = ind.atr(highs, lows, closes, 14)
    # 60-day ATR proxy: ATR(14) ratio
    if a is None or closes[-1] <= 0:
        return False, None
    ratio = a / closes[-1]
    if ratio > 0.04:
        return True, f"ATR {ratio*100:.1f}%"
    return False, None


# ----------------------------- SENTIMENT ----------------------------- #

def _sig_hype_exhaustion(news):
    if not news:
        return False, None
    now = datetime.now()
    last7 = 0
    prior30 = 0
    for n in news:
        ts = n.get('providerPublishTime') or n.get('content', {}).get('pubDate')
        if isinstance(ts, str):
            try:
                ts_dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                continue
        elif isinstance(ts, (int, float)):
            ts_dt = datetime.fromtimestamp(ts)
        else:
            continue
        age = (now - ts_dt).days
        if age <= 7:
            last7 += 1
        elif age <= 30:
            prior30 += 1
    prior_avg_per_week = prior30 / (23 / 7) if prior30 else 0
    if prior_avg_per_week >= 2 and last7 < 0.5 * prior_avg_per_week:
        return True, f"news drought {last7}/wk vs {prior_avg_per_week:.1f}"
    return False, None


def _sig_negative_sentiment(news):
    if not news:
        return False, None
    neg_kw = ('miss', 'downgrade', 'cut', 'concern', 'lawsuit', 'probe', 'decline', 'warning', 'fraud')
    pos_kw = ('beat', 'upgrade', 'raise', 'strong', 'record', 'surge', 'rally')
    neg = pos = 0
    for n in news[:10]:
        title = (n.get('title') or n.get('content', {}).get('title') or '').lower()
        if any(k in title for k in neg_kw):
            neg += 1
        if any(k in title for k in pos_kw):
            pos += 1
    if neg > pos and neg >= 2:
        return True, f"news sentiment -{neg}/+{pos}"
    return False, None


# ============================ ORCHESTRATION ========================== #

PILLARS = {
    'technical':   ('sma_break', 'sma_slope', 'death_cross', 'weekly_lh', 'distribution'),
    'fundamental': ('pe_extreme', 'ev_ebitda', 'rev_decel', 'neg_revisions'),
    'quant':       ('stretched', 'high_atr'),
    'sentiment':   ('hype_exhaust', 'neg_sent'),
}


def _evaluate(symbol):
    df = df_mod.fetch_ohlcv(symbol, days=500)
    if df is None or len(df) < 210:
        return None
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    idx = df.index

    info = df_mod.fetch_info(symbol) or {}
    revs = df_mod.fetch_quarterly_revenue(symbol) or []
    ups, downs = df_mod.fetch_recommendations(symbol, days=90)
    try:
        import yfinance as yf
        news = yf.Ticker(symbol).news or []
    except (ValueError, KeyError, AttributeError, ConnectionError):
        news = []

    fires = {}

    def _put(key, res):
        fired, label = res
        if fired and label:
            fires[key] = label

    _put('sma_break',    _sig_close_below_sma200(closes))
    _put('sma_slope',    _sig_sma200_slope_neg(closes))
    _put('death_cross',  _sig_death_cross(closes))
    _put('weekly_lh',    _sig_weekly_lower_highs(idx, closes))
    _put('distribution', _sig_distribution_top(closes))

    _put('pe_extreme',    _sig_pe_extreme(info))
    _put('ev_ebitda',     _sig_ev_ebitda(info))
    _put('rev_decel',     _sig_rev_decel(revs))
    _put('neg_revisions', _sig_negative_revisions(ups, downs))

    _put('stretched', _sig_stretched_above_sma(closes))
    _put('high_atr',  _sig_high_atr(highs, lows, closes))

    _put('hype_exhaust', _sig_hype_exhaustion(news))
    _put('neg_sent',     _sig_negative_sentiment(news))

    pillars_hit = sum(1 for keys in PILLARS.values() if any(k in fires for k in keys))
    return {
        'symbol': symbol,
        'closes': closes,
        'highs': highs,
        'lows': lows,
        'fires': fires,
        'pillars_hit': pillars_hit,
        'n_fires': len(fires),
    }


def analyze(symbol, force=False):
    ev = _evaluate(symbol)
    if ev is None:
        return None
    n = ev['n_fires']
    pillars = ev['pillars_hit']

    if force:
        threshold_ok = n >= 1
    else:
        threshold_ok = (n >= 3 and pillars >= 2)
    if not threshold_ok:
        return None

    closes = ev['closes']
    if pillars >= 3:
        trim_pct, action = 75, 'full_thesis_review'
    else:
        trim_pct, action = 50, 'thesis_review'

    reasons = list(ev['fires'].values())
    rsi_v = ind.rsi(closes, 14)
    atr_v = ind.atr(ev['highs'], ev['lows'], closes, 14)
    atr_pct = (atr_v / closes[-1] * 100) if atr_v else None
    feats = {
        'rsi': rsi_v, 'macd_cross': False, 'adx': None,
        'mtf_confirm': 'weekly_lh' in ev['fires'],
        'divergence': False, 'atr_pct': atr_pct, 'reasons': reasons,
    }
    conf, breakdown = scorer.score(symbol, feats, side='secular_top', pillars_hit=pillars)

    return {
        'symbol': symbol,
        'category': 'secular_top',
        'reasons': reasons,
        'pillars_hit': pillars,
        'n_signals': n,
        'confidence': conf,
        'breakdown': breakdown,
        'current_price': round(float(closes[-1]), 2),
        'trim_pct': trim_pct,
        'action': action,
    }


def detect(symbols, force=False):
    out = []
    for s in symbols:
        try:
            r = analyze(s.upper(), force=force)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError) as e:
            print(f"[{s}] error: {e}", file=sys.stderr)
            continue
        if r:
            out.append(r)
    return sorted(out, key=lambda x: -x['confidence'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', nargs='+', default=[])
    p.add_argument('symbols', nargs='*')
    p.add_argument('--force', action='store_true')
    p.add_argument('--min-conf', type=float, default=0.0)
    args = p.parse_args()
    syms = args.symbol + args.symbols
    if not syms:
        p.error('Provide at least one symbol')
    results = detect(syms, force=args.force)
    results = [r for r in results if r['confidence'] >= args.min_conf]
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
