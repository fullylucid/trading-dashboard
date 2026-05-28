#!/usr/bin/env python3
"""Charlotte 365d backtest.
For each detector signal fired historically, simulate:
  - momentum_trim: trim 30% at signal, hold remaining 70% as buy-and-hold core
  - secular_top: trim 50%
  - trough: add 25% to existing position
Compare scale-out / scale-in vs pure buy-and-hold.
"""
import sys, argparse, json
import numpy as np
from datetime import datetime, timedelta

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte import indicators as ind
from charlotte import data_fetch as df_mod


HORIZON = 30  # bars forward to evaluate vs buy-and-hold


def _momentum_signal(closes, highs, lows, vols, opens, i):
    if i < 60: return False, []
    rsi_v = ind.rsi(closes[:i+1], 14)
    macd_now, macd_prev = ind.macd_hist(closes[:i+1])
    adx_v = ind.adx(highs[:i+1], lows[:i+1], closes[:i+1], 14)
    med_vol = np.median(vols[max(0, i-60):i+1])
    vol_ratio = vols[i] / med_vol if med_vol > 0 else 1
    red = closes[i] < opens[i]
    reasons = []
    if rsi_v and rsi_v > 75: reasons.append('rsi')
    if macd_prev is not None and macd_now is not None and macd_prev > 0 and macd_now < 0: reasons.append('macd')
    if vol_ratio > 2 and red: reasons.append('vol')
    if adx_v and adx_v >= 25: reasons.append('adx')
    return len(reasons) >= 2, reasons


def _trough_signal(closes, highs, lows, vols, opens, i):
    if i < 60: return False, []
    rsi_v = ind.rsi(closes[:i+1], 14)
    macd_now, macd_prev = ind.macd_hist(closes[:i+1])
    med_vol = np.median(vols[max(0, i-60):i+1])
    vol_ratio = vols[i] / med_vol if med_vol > 0 else 1
    green = closes[i] > opens[i]
    prior_down = sum(1 for j in range(max(1, i-4), i) if closes[j] < closes[j-1])
    reasons = []
    if rsi_v and rsi_v < 30: reasons.append('rsi')
    if macd_prev is not None and macd_now is not None and macd_prev < 0 and macd_now > 0: reasons.append('macd')
    if vol_ratio > 2 and green and prior_down >= 2: reasons.append('cap')
    if i >= 200:
        s200 = np.mean(closes[i-199:i+1])
        if closes[i] < s200 * 0.85: reasons.append('sma')
    return len(reasons) >= 2, reasons


def _secular_signal(closes, i):
    if i < 220: return False, []
    s200 = [np.mean(closes[j-199:j+1]) for j in range(i-2, i+1)]
    last3_below = all(closes[i-2+k] < s200[k] for k in range(3))
    s_series = np.array([np.mean(closes[j-199:j+1]) for j in range(i-19, i+1)])
    slope = np.polyfit(np.arange(20), s_series, 1)[0]
    reasons = []
    if last3_below: reasons.append('sma_break')
    if slope < 0: reasons.append('slope_neg')
    return len(reasons) >= 2, reasons


def backtest_symbol(symbol, days=365):
    df = df_mod.fetch_ohlcv(symbol, days=days + 250)
    if df is None: return None
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    opens = df['Open'].values.flatten()
    vols = df['Volume'].values.flatten()
    n = len(closes)
    start_i = max(220, n - days)

    trims, secs, adds = [], [], []
    last_mt = -10; last_st = -30; last_tr = -10
    for i in range(start_i, n - HORIZON):
        if i - last_mt > 10:
            fire, _ = _momentum_signal(closes, highs, lows, vols, opens, i)
            if fire:
                last_mt = i
                entry = closes[i]; exit_p = closes[i + HORIZON]
                # scale-out: 30% locked at entry, 70% rides to exit
                so_ret = 0.3 * 0 + 0.7 * (exit_p - entry) / entry  # 30% trimmed = 0 further P/L
                bh_ret = (exit_p - entry) / entry
                trims.append((so_ret, bh_ret))
        if i - last_st > 30:
            fire, _ = _secular_signal(closes, i)
            if fire:
                last_st = i
                entry = closes[i]; exit_p = closes[i + HORIZON]
                so_ret = 0.5 * 0 + 0.5 * (exit_p - entry) / entry
                bh_ret = (exit_p - entry) / entry
                secs.append((so_ret, bh_ret))
        if i - last_tr > 10:
            fire, _ = _trough_signal(closes, highs, lows, vols, opens, i)
            if fire:
                last_tr = i
                entry = closes[i]; exit_p = closes[i + HORIZON]
                # add 25%: cost basis blend
                add_ret = 1.25 * (exit_p - entry) / entry
                bh_ret = (exit_p - entry) / entry
                adds.append((add_ret, bh_ret))
    return {'momentum_trim': trims, 'secular_top': secs, 'trough': adds}


def summarize(by_symbol):
    cat_results = {'momentum_trim': [], 'secular_top': [], 'trough': []}
    for sym, r in by_symbol.items():
        if r is None: continue
        for k in cat_results:
            cat_results[k].extend(r[k])
    out = {}
    for cat, lst in cat_results.items():
        if not lst:
            out[cat] = {'n': 0}
            continue
        diffs = [s - b for s, b in lst]  # strategy - buy-and-hold
        wins = sum(1 for d in diffs if d > 0)
        out[cat] = {
            'n': len(lst),
            'win_rate': round(wins / len(lst), 3),
            'avg_strategy_ret': round(np.mean([s for s, _ in lst]) * 100, 2),
            'avg_bh_ret': round(np.mean([b for _, b in lst]) * 100, 2),
            'avg_outperformance_pct': round(np.mean(diffs) * 100, 2),
            'median_outperformance_pct': round(np.median(diffs) * 100, 2),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='+', required=True)
    ap.add_argument('--days', type=int, default=365)
    args = ap.parse_args()

    by_symbol = {}
    for s in args.symbols:
        print(f"Backtesting {s}...", file=sys.stderr)
        try:
            by_symbol[s] = backtest_symbol(s.upper(), args.days)
        except (ValueError, KeyError, AttributeError, IndexError) as e:
            print(f"[{s}] error: {e}", file=sys.stderr)
            by_symbol[s] = None

    summary = summarize(by_symbol)
    print(json.dumps({'days': args.days, 'symbols': list(by_symbol.keys()), 'summary': summary}, indent=2))

    # Pretty table
    print("\nCategory          n   win%   strat%   B&H%   edge%  median-edge%", file=sys.stderr)
    print("-" * 70, file=sys.stderr)
    for cat, r in summary.items():
        if r.get('n', 0) == 0:
            print(f"{cat:18s} {0}", file=sys.stderr); continue
        print(f"{cat:18s} {r['n']:<3d} {r['win_rate']*100:5.1f}  {r['avg_strategy_ret']:6.2f}  "
              f"{r['avg_bh_ret']:6.2f}  {r['avg_outperformance_pct']:6.2f}  {r['median_outperformance_pct']:6.2f}",
              file=sys.stderr)


if __name__ == '__main__':
    main()
