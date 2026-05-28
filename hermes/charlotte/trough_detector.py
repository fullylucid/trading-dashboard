#!/usr/bin/env python3
"""Charlotte Trough Detector v2.

Eleven signals across four pillars (technical / fundamental / quant /
sentiment). HIGH-confidence fire requires >=3 signals across >=2 pillars.
Pillars-hit >= 3 -> core_add 20%.
Else                core_add 10%.

Public API preserved:
    detect(symbols: list) -> list[dict]
    CLI:  python -m charlotte.trough_detector --symbol AAPL [--force]
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

def _sig_rsi_oversold(closes):
    r = ind.rsi(closes, 14)
    if r is None:
        return False, None
    if r < 30:
        return True, f"RSI {r:.1f}<30"
    rsis = ind.rsi_series(closes, 14)
    if r < 35 and ind.bullish_rsi_divergence(closes, rsis, 20):
        return True, f"RSI {r:.1f}+bull-div"
    return False, None


def _sig_macd_bull_cross(closes):
    now, prev = ind.macd_hist(closes)
    if now is None or prev is None:
        return False, None
    if prev < 0 and now > 0:
        return True, "MACD bull cross"
    return False, None


def _sig_capitulation(opens, closes, vols):
    if len(vols) < 60:
        return False, None
    med = float(np.median(vols[-60:]))
    if med <= 0:
        return False, None
    vr = float(vols[-1] / med)
    green = closes[-1] > opens[-1]
    prior_down = sum(1 for i in range(-4, 0) if closes[i] < closes[i - 1])
    if vr > 2.0 and green and prior_down >= 3:
        return True, f"Capitulation vol {vr:.1f}x"
    return False, None


def _sig_sma200_reclaim(closes):
    if len(closes) < 210:
        return False, None
    s = pd.Series(closes).rolling(200).mean().values
    if np.isnan(s[-1]):
        return False, None
    if closes[-1] <= s[-1]:
        return False, None
    # recent low (last 10 bars before today) was under 200SMA
    for i in range(-11, -1):
        if not np.isnan(s[i]) and closes[i] < s[i]:
            return True, "Reclaim 200SMA"
    return False, None


# ----------------------------- FUNDAMENTAL --------------------------- #

def _sig_pe_compressed(info):
    pe = info.get('trailingPE') or info.get('forwardPE')
    if not pe or pe <= 0:
        return False, None
    if pe < 15:
        return True, f"P/E {pe:.1f} compressed"
    return False, None


def _sig_ev_ebitda_low(info):
    ev = info.get('enterpriseToEbitda')
    if ev is None or ev <= 0:
        return False, None
    if ev < 12:
        return True, f"EV/EBITDA {ev:.1f}"
    return False, None


def _sig_rev_reaccel(revs):
    if len(revs) < 7:
        return False, None
    yoys = []
    for i in range(3):
        if revs[i + 4]:
            yoys.append((revs[i] - revs[i + 4]) / abs(revs[i + 4]))
    if len(yoys) < 3:
        return False, None
    # yoys[0]=most recent quarter; reaccel = most recent > avg of prior two
    prior_avg = (yoys[1] + yoys[2]) / 2
    if yoys[0] > prior_avg + 0.02:
        return True, f"Rev YoY reaccel {yoys[0]*100:.0f}%"
    return False, None


def _sig_positive_revisions(ups, downs):
    if ups > downs and ups >= 2:
        return True, f"upgrades {ups}>{downs}"
    return False, None


# ----------------------------- QUANT --------------------------------- #

def _sig_stretched_below(closes):
    s200 = ind.sma(closes, 200)
    if s200 is None or s200 <= 0:
        return False, None
    stretch = closes[-1] / s200 - 1
    if stretch < -0.15:
        return True, f"{stretch*100:.0f}% below 200SMA"
    return False, None


def _sig_low_atr(highs, lows, closes):
    a = ind.atr(highs, lows, closes, 14)
    if a is None or closes[-1] <= 0:
        return False, None
    ratio = a / closes[-1]
    if ratio < 0.02:
        return True, f"ATR compressed {ratio*100:.1f}%"
    return False, None


def _sig_sharpe_recovery(closes):
    if len(closes) < 80:
        return False, None
    rets = np.diff(closes[-61:]) / closes[-61:-1]
    if len(rets) < 30 or np.std(rets) == 0:
        return False, None
    sharpe = float(np.mean(rets) / np.std(rets))
    # require recent drawdown of 10%+ from 120-bar high
    high = float(np.max(closes[-120:])) if len(closes) >= 120 else float(np.max(closes))
    dd = closes[-1] / high - 1
    if sharpe > 0 and dd < -0.10:
        return True, f"Sharpe+ post-DD {dd*100:.0f}%"
    return False, None


# ----------------------------- SENTIMENT ----------------------------- #

def _sig_news_surge_positive(news):
    if not news:
        return False, None
    now = datetime.now()
    last7 = 0
    prior30 = 0
    pos_kw = ('beat', 'beats', 'surge', 'rally', 'upgrade', 'strong', 'record', 'soar', 'jump', 'breakthrough')
    neg_kw = ('miss', 'misses', 'plunge', 'cut', 'downgrade', 'weak', 'lawsuit', 'probe', 'warning', 'fraud')
    pos = neg = 0
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
            title = (n.get('title') or n.get('content', {}).get('title') or '').lower()
            if any(k in title for k in pos_kw): pos += 1
            if any(k in title for k in neg_kw): neg += 1
        elif age <= 37:
            prior30 += 1
    prior_avg_week = prior30 / (30 / 7) if prior30 else 0
    if last7 > 1.5 * max(prior_avg_week, 1) and pos > neg:
        return True, f"news surge +{pos}/-{neg}"
    return False, None


def _sig_positive_recs(ups, downs):
    if ups - downs >= 2:
        return True, f"net upgrades +{ups - downs}"
    return False, None


# ============================ ORCHESTRATION ========================== #

PILLARS = {
    'technical':   ('rsi_os', 'macd_cross', 'capitulation', 'sma_reclaim'),
    'fundamental': ('pe_low', 'ev_low', 'rev_reaccel', 'pos_revisions'),
    'quant':       ('stretched_dn', 'low_atr', 'sharpe_rec'),
    'sentiment':   ('news_surge', 'pos_recs'),
}


def _evaluate(symbol):
    df = df_mod.fetch_ohlcv(symbol, days=500)
    if df is None or len(df) < 60:
        return None
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    opens = df['Open'].values.flatten()
    vols = df['Volume'].values.flatten()

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

    _put('rsi_os',       _sig_rsi_oversold(closes))
    _put('macd_cross',   _sig_macd_bull_cross(closes))
    _put('capitulation', _sig_capitulation(opens, closes, vols))
    _put('sma_reclaim',  _sig_sma200_reclaim(closes))

    _put('pe_low',         _sig_pe_compressed(info))
    _put('ev_low',         _sig_ev_ebitda_low(info))
    _put('rev_reaccel',    _sig_rev_reaccel(revs))
    _put('pos_revisions',  _sig_positive_revisions(ups, downs))

    _put('stretched_dn', _sig_stretched_below(closes))
    _put('low_atr',      _sig_low_atr(highs, lows, closes))
    _put('sharpe_rec',   _sig_sharpe_recovery(closes))

    _put('news_surge', _sig_news_surge_positive(news))
    _put('pos_recs',   _sig_positive_recs(ups, downs))

    pillars_hit = sum(1 for keys in PILLARS.values() if any(k in fires for k in keys))
    return {
        'symbol': symbol, 'closes': closes, 'highs': highs, 'lows': lows,
        'fires': fires, 'pillars_hit': pillars_hit, 'n_fires': len(fires),
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
        add_pct, action = 20, 'core_add'
    else:
        add_pct, action = 10, 'add'

    reasons = list(ev['fires'].values())
    rsi_v = ind.rsi(closes, 14)
    atr_v = ind.atr(ev['highs'], ev['lows'], closes, 14)
    atr_pct = (atr_v / closes[-1] * 100) if atr_v else None
    feats = {
        'rsi': rsi_v, 'macd_cross': 'macd_cross' in ev['fires'], 'adx': None,
        'mtf_confirm': False,
        'divergence': any('div' in r.lower() for r in reasons),
        'atr_pct': atr_pct, 'reasons': reasons,
    }
    conf, breakdown = scorer.score(symbol, feats, side='trough', pillars_hit=pillars)

    return {
        'symbol': symbol,
        'category': 'trough',
        'reasons': reasons,
        'pillars_hit': pillars,
        'n_signals': n,
        'confidence': conf,
        'breakdown': breakdown,
        'current_price': round(float(closes[-1]), 2),
        'add_pct': add_pct,
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
