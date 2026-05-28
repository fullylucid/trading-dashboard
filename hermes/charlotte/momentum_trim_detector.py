#!/usr/bin/env python3
"""Momentum trim detector: short-term peak signals (RSI/MACD/Vol/ADX/MTF).
Fires when 2+ signals agree. Output JSON list to stdout.
"""
import sys, json, argparse
import numpy as np

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte import indicators as ind
from charlotte import data_fetch as df_mod
from charlotte import multi_factor_scorer as scorer


_TECH_KW = ('rsi', 'macd', 'adx', 'sma', 'vol', 'climax', 'weekly', 'div', 'capitulat', '200')
_FUND_KW = ('pe', 'p/e', 'rev', 'growth', 'ebitda', 'downgrade', 'upgrade', 'revision')
_QUANT_KW = ('atr', 'stretch', 'quant', 'sharpe', 'compress')
_SENT_KW = ('sentiment', 'news', 'recs', 'recommend', 'hype', 'drought', 'washout')


def _infer_pillars(reasons, atr_pct=None):
    """Infer count of distinct pillars hit from signal-tag keywords."""
    pillars = set()
    for r in reasons:
        low = r.lower()
        if any(k in low for k in _TECH_KW): pillars.add('t')
        if any(k in low for k in _FUND_KW): pillars.add('f')
        if any(k in low for k in _QUANT_KW): pillars.add('q')
        if any(k in low for k in _SENT_KW): pillars.add('s')
    # atr_pct is a quant feature even if not in reason strings
    if atr_pct is not None and atr_pct > 4:
        pillars.add('q')
    return len(pillars)


def _dyn_trail_pct(atr_pct):
    """ATR-based dynamic trail: max(10%, 2.5*ATR%) capped at 15%.
    Wider in volatile names so a routine wiggle doesn't kick us out,
    but ceilinged so we still book gains in the wildest movers."""
    if atr_pct is None:
        return 10.0
    return float(max(10.0, min(15.0, 2.5 * atr_pct)))


def analyze(symbol, force=False, min_pillars=3):
    df = df_mod.fetch_ohlcv(symbol)
    if df is None:
        return None
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    opens = df['Open'].values.flatten()
    vols = df['Volume'].values.flatten()
    if len(closes) < 60:
        return None

    rsi_v = ind.rsi(closes, 14)
    macd_now, macd_prev = ind.macd_hist(closes)
    adx_v = ind.adx(highs, lows, closes, 14)
    atr_v = ind.atr(highs, lows, closes, 14)
    atr_pct = (atr_v / closes[-1] * 100) if atr_v else None

    rsis = ind.rsi_series(closes, 14)
    diverg = ind.bearish_rsi_divergence(closes, rsis, 20)

    weekly = df_mod.fetch_weekly_rsi_series(symbol)
    weekly_rsi = ind.rsi(weekly, 14) if weekly is not None else None
    mtf_confirm = bool(weekly_rsi is not None and weekly_rsi > 65)

    med_vol = float(np.median(vols[-60:])) if len(vols) >= 60 else float(np.median(vols))
    vol_ratio = float(vols[-1] / med_vol) if med_vol > 0 else 1.0
    red_candle = closes[-1] < opens[-1]
    vol_climax = vol_ratio > 2.0 and red_candle

    macd_cross = macd_prev is not None and macd_now is not None and macd_prev > 0 and macd_now < 0

    reasons = []
    if rsi_v is not None and rsi_v > 75:
        reasons.append(f"RSI {rsi_v:.1f}>75")
    elif rsi_v is not None and rsi_v > 70 and diverg:
        reasons.append(f"RSI {rsi_v:.1f}+bear-div")
    if macd_cross:
        reasons.append("MACD bear cross")
    if vol_climax:
        reasons.append(f"Vol climax {vol_ratio:.1f}x")
    if adx_v is not None and adx_v >= 25:
        reasons.append(f"ADX {adx_v:.0f}")
    if mtf_confirm:
        reasons.append(f"Weekly RSI {weekly_rsi:.0f}")

    threshold = 1 if force else 3
    if len(reasons) < threshold:
        return None

    feats = {
        'rsi': rsi_v, 'macd_cross': macd_cross, 'adx': adx_v,
        'mtf_confirm': mtf_confirm, 'divergence': diverg,
        'atr_pct': atr_pct, 'reasons': reasons,
    }
    pillars = _infer_pillars(reasons, atr_pct)

    # Regime gate: in SPY bull regime, require pillars >= 4 (else >= min_pillars).
    bull, _ = df_mod.spy_bull_regime()
    required_pillars = max(min_pillars, 4 if bull else min_pillars)
    if not force and pillars < required_pillars:
        return None

    conf, breakdown = scorer.score(symbol, feats, side='peak', pillars_hit=pillars)

    # Pick trim 25-35 based on confidence; default 30
    trim_pct = 25 + min(10, int(conf))  # conf 5 -> 30, conf 10 -> 35
    trim_pct = max(25, min(35, trim_pct))

    trail_pct = round(_dyn_trail_pct(atr_pct), 1)

    return {
        'symbol': symbol,
        'category': 'momentum_trim',
        'reasons': reasons,
        'pillars_hit': pillars,
        'n_signals': len(reasons),
        'required_pillars': required_pillars,
        'spy_bull': bull,
        'confidence': conf,
        'breakdown': breakdown,
        'current_price': round(float(closes[-1]), 2),
        'atr_pct': round(atr_pct, 2) if atr_pct else None,
        'trim_pct': trim_pct,
        'trail_pct': trail_pct,
        'action': 'TRIM',
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', nargs='+', required=True)
    p.add_argument('--force', action='store_true', help='Fire on 1+ signal (for example/testing)')
    p.add_argument('--min-pillars', type=int, default=3, help='Min pillars (default 3, bumped to 4 in SPY bull regime)')
    args = p.parse_args()
    out = []
    for s in args.symbol:
        print(f"[momentum_trim] scanning {s}", file=sys.stderr)
        try:
            r = analyze(s.upper(), force=args.force, min_pillars=args.min_pillars)
        except (ValueError, KeyError, AttributeError, IndexError) as e:
            print(f"[{s}] error: {e}", file=sys.stderr); continue
        if r: out.append(r)
    print(json.dumps(sorted(out, key=lambda x: -x['confidence']), indent=2))


if __name__ == '__main__':
    main()
