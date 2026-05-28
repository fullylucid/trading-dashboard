#!/usr/bin/env python3
"""Charlotte secular-top backtest: v1 (legacy 96-LOC detector) vs v2 (13-signal).

For each historical bar in the trailing window we evaluate both detectors
point-in-time using only bar-derived signals (fundamentals/news are not
back-testable without a historical fundamentals feed, so the fundamental and
sentiment pillars are skipped during the walk-forward — we use the technical
and quant pillars only, matching the data the legacy v1 actually had access
to historically).

For each fire date we measure the subsequent 60-bar return. A fire is a
"win" if forward-return is negative (a trim would have protected capital).
We report n_fires, win_rate, avg_60d_return, and avg_capital_saved (which
is trim_pct * max(0, -forward_return) averaged across all fires).
"""
from __future__ import annotations
import sys
import json
import argparse
import numpy as np
import pandas as pd

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte import data_fetch as df_mod

HORIZON = 60


# --------------------- v1 legacy logic (point in time) --------------------- #

def v1_fire(closes, i):
    """Legacy detector: 2+ of {3d<200SMA, slope_neg}. Fundamentals skipped."""
    if i < 220:
        return False, []
    seg = closes[:i + 1]
    s = pd.Series(seg).rolling(200).mean().values
    if np.isnan(s[-3]):
        return False, []
    reasons = []
    if np.all(seg[-3:] < s[-3:]):
        reasons.append('sma_break')
    s20 = s[-20:]
    if not np.isnan(s20).any():
        slope = np.polyfit(np.arange(20), s20, 1)[0]
        if slope < 0:
            reasons.append('slope_neg')
    return len(reasons) >= 2, reasons


# --------------------- v2 technical+quant subset (point in time) ----------- #

def v2_fire(closes, highs, lows, idx, i):
    if i < 220:
        return False, [], 0
    seg = closes[:i + 1]
    sh = highs[:i + 1]
    sl = lows[:i + 1]

    fires = {}
    s_series = pd.Series(seg).rolling(200).mean().values

    # 1. close < 200SMA 3d
    if not np.isnan(s_series[-3]) and np.all(seg[-3:] < s_series[-3:]):
        fires['sma_break'] = 'technical'

    # 2. 200SMA slope neg
    s20 = s_series[-20:]
    if not np.isnan(s20).any():
        slope = np.polyfit(np.arange(20), s20, 1)[0]
        if slope < 0:
            fires['sma_slope'] = 'technical'

    # 3. death cross last 30d
    s50 = pd.Series(seg).rolling(50).mean().values
    lb = 31
    if len(s50) >= lb and not np.isnan(s50[-lb:]).any() and not np.isnan(s_series[-lb:]).any():
        diff = s50[-lb:] - s_series[-lb:]
        if np.any((diff[:-1] > 0) & (diff[1:] <= 0)):
            fires['death_cross'] = 'technical'

    # 4. weekly lower highs (resample)
    try:
        sub_idx = idx[:i + 1]
        ws = pd.Series(seg, index=sub_idx).resample('W').max().dropna().values
        if len(ws) >= 12:
            peaks = [j for j in range(1, len(ws) - 1) if ws[j] > ws[j - 1] and ws[j] > ws[j + 1]]
            if len(peaks) >= 3:
                last3 = [ws[j] for j in peaks[-3:]]
                if last3[0] > last3[1] > last3[2]:
                    fires['weekly_lh'] = 'technical'
    except (TypeError, ValueError):
        pass

    # 5. distribution / double top
    if len(seg) >= 250:
        peaks = []
        for k in range(20, len(seg) - 20):
            if seg[k] == max(seg[k - 20:k + 21]):
                peaks.append((k, seg[k]))
        if len(peaks) >= 2:
            peaks.sort(key=lambda x: -x[1])
            top1 = peaks[0]
            cands = [p for p in peaks[1:] if abs(p[0] - top1[0]) >= 60 and abs(p[1] - top1[1]) / top1[1] < 0.05]
            if cands:
                level = (top1[1] + cands[0][1]) / 2
                if abs(seg[-1] - level) / level < 0.05:
                    fires['distribution'] = 'technical'

    # 10. stretched > 30% over 200SMA  (quant)
    sma200 = s_series[-1]
    if not np.isnan(sma200) and sma200 > 0:
        if seg[-1] / sma200 - 1 > 0.30:
            fires['stretched'] = 'quant'

    # 11. ATR high
    tr = np.maximum.reduce([
        sh[1:] - sl[1:],
        np.abs(sh[1:] - seg[:-1]),
        np.abs(sl[1:] - seg[:-1]),
    ])
    atr_v = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    if seg[-1] > 0 and atr_v / seg[-1] > 0.04:
        fires['high_atr'] = 'quant'

    pillars = len(set(fires.values()))
    n = len(fires)
    fired = (n >= 3 and pillars >= 2)
    return fired, list(fires.keys()), pillars


# ------------------------------ walk-forward ------------------------------- #

def walk_symbol(symbol, days=365):
    df = df_mod.fetch_ohlcv(symbol, days=days + 320)
    if df is None:
        return None
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    idx = df.index
    n = len(closes)
    start_i = max(220, n - days)

    v1_fires, v2_fires = [], []
    last_v1 = -30
    last_v2 = -30
    for i in range(start_i, n - HORIZON):
        fwd = (closes[i + HORIZON] - closes[i]) / closes[i]
        if i - last_v1 >= 30:
            fired, _ = v1_fire(closes, i)
            if fired:
                v1_fires.append(fwd)
                last_v1 = i
        if i - last_v2 >= 30:
            fired, _, pillars = v2_fire(closes, highs, lows, idx, i)
            if fired:
                trim_pct = 0.75 if pillars >= 3 else 0.50
                v2_fires.append((fwd, trim_pct))
                last_v2 = i
    return v1_fires, v2_fires


def summarize(label, fires):
    """fires is either list[float] (v1) or list[(float, trim_pct)] (v2)."""
    if not fires:
        return {'detector': label, 'n_fires': 0, 'win_rate': None,
                'avg_60d_ret_pct': None, 'median_60d_ret_pct': None,
                'avg_capital_saved_pct': None}
    if isinstance(fires[0], tuple):
        rets = np.array([r for r, _ in fires])
        trims = np.array([t for _, t in fires])
    else:
        rets = np.array(fires)
        trims = np.full(len(fires), 0.5)
    wins = int((rets < 0).sum())
    saved = np.where(rets < 0, -rets * trims, 0.0)
    return {
        'detector': label,
        'n_fires': len(fires),
        'win_rate': round(wins / len(fires), 3),
        'avg_60d_ret_pct': round(float(rets.mean()) * 100, 2),
        'median_60d_ret_pct': round(float(np.median(rets)) * 100, 2),
        'avg_capital_saved_pct': round(float(saved.mean()) * 100, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='+', required=True)
    ap.add_argument('--days', type=int, default=365)
    args = ap.parse_args()

    all_v1, all_v2 = [], []
    for s in args.symbols:
        print(f"backtest {s}...", file=sys.stderr)
        try:
            r = walk_symbol(s.upper(), args.days)
        except (ValueError, KeyError, AttributeError, IndexError) as e:
            print(f"[{s}] {e}", file=sys.stderr); continue
        if r is None:
            continue
        v1, v2 = r
        all_v1.extend(v1)
        all_v2.extend(v2)

    s1 = summarize('v1_legacy', all_v1)
    s2 = summarize('v2_13signal', all_v2)
    print(json.dumps({'days': args.days, 'symbols': args.symbols, 'v1': s1, 'v2': s2}, indent=2))

    hdr = f"{'detector':<14}{'n':>5}{'win%':>8}{'avg60d%':>10}{'med60d%':>10}{'cap_saved%':>12}"
    print("\n" + hdr, file=sys.stderr)
    print('-' * len(hdr), file=sys.stderr)
    for r in (s1, s2):
        if r['n_fires'] == 0:
            print(f"{r['detector']:<14}{0:>5}", file=sys.stderr); continue
        print(f"{r['detector']:<14}{r['n_fires']:>5}{r['win_rate']*100:>7.1f} "
              f"{r['avg_60d_ret_pct']:>9.2f} {r['median_60d_ret_pct']:>9.2f} "
              f"{r['avg_capital_saved_pct']:>11.2f}", file=sys.stderr)


if __name__ == '__main__':
    main()
