#!/usr/bin/env python3
"""Charlotte unified scale-out backtest.

Simulates this exact policy over a trailing window per symbol, starting from a
$10K position:

  momentum_trim fire  -> sell 30% (cash booked at signal price), keep rest,
                         trail remaining at 7% off subsequent peak.
  secular_top fire    -> sell 50% (75% if 3+ pillars), keep rest.
  trough fire         -> buy +15% of original $10K (20% if 3+ pillars),
                         using fresh cash; track cost basis at signal price.

At window end, liquidate everything at last close.

Compares scale-out total return vs buy-and-hold $10K.

Note: like secular_top_backtest, we evaluate detectors point-in-time using
technical + quant features only (no historical fundamentals/news feed).
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

INITIAL = 10_000.0
COOLDOWN = 15  # min bars between fires within one category


# ----------------------- point-in-time detectors ----------------------- #

def _series(closes):
    return pd.Series(closes)


def _sma(closes, w):
    if len(closes) < w:
        return np.full(len(closes), np.nan)
    return _series(closes).rolling(w).mean().values


def _rsi_pit(closes, period=14):
    if len(closes) < period + 1:
        return None
    d = np.diff(closes)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag = float(np.mean(g[:period])); al = float(np.mean(l[:period]))
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_hist_pit(closes):
    if len(closes) < 35:
        return None, None
    s = _series(closes)
    ef = s.ewm(span=12, adjust=False).mean().values
    es = s.ewm(span=26, adjust=False).mean().values
    macd = ef - es
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    h = macd - sig
    return float(h[-1]), float(h[-2])


def _atr_pit(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - closes[:-1]),
        np.abs(lows[1:] - closes[:-1]),
    ])
    return float(pd.Series(tr).ewm(alpha=1/period, adjust=False).mean().iloc[-1])


def momentum_fire(closes, highs, lows, vols, opens, i, min_pillars=2):
    """Return (fired, pillars, atr_pct) where atr_pct is current ATR/price*100.

    v3 used min_pillars=2 implicitly via 2+ reasons; v3.1 demands >=3 (or >=4 in
    SPY bull regime, gated by caller).
    """
    if i < 60:
        return False, 0, None
    cs = closes[:i + 1]; hs = highs[:i + 1]; ls = lows[:i + 1]
    vs = vols[:i + 1]; os_ = opens[:i + 1]
    r = _rsi_pit(cs, 14)
    mh, mp = _macd_hist_pit(cs)
    reasons = 0
    pillars = set()
    if r is not None and r > 75:
        reasons += 1; pillars.add('t')
    if mh is not None and mp is not None and mp > 0 and mh < 0:
        reasons += 1; pillars.add('t')
    med = float(np.median(vs[-60:])) if len(vs) >= 60 else 0
    if med > 0 and vs[-1] / med > 2.0 and cs[-1] < os_[-1]:
        reasons += 1; pillars.add('t')
    a = _atr_pit(hs, ls, cs, 14)
    atr_pct = (a / cs[-1] * 100) if (a is not None and cs[-1] > 0) else None
    if atr_pct is not None and atr_pct > 4:
        reasons += 1; pillars.add('q')
    fired = reasons >= max(2, min_pillars) and len(pillars) >= min_pillars
    return fired, len(pillars), atr_pct


def secular_fire(closes, highs, lows, idx, i):
    if i < 220:
        return False, 0
    seg = closes[:i + 1]; sh = highs[:i + 1]; sl = lows[:i + 1]
    s200 = _sma(seg, 200)
    fires = {}
    if not np.isnan(s200[-3]) and np.all(seg[-3:] < s200[-3:]):
        fires['sma_break'] = 't'
    s20 = s200[-20:]
    if not np.isnan(s20).any():
        slope = np.polyfit(np.arange(20), s20, 1)[0]
        if slope < 0:
            fires['sma_slope'] = 't'
    s50 = _sma(seg, 50)
    lb = 31
    if len(s50) >= lb and not np.isnan(s50[-lb:]).any() and not np.isnan(s200[-lb:]).any():
        diff = s50[-lb:] - s200[-lb:]
        if np.any((diff[:-1] > 0) & (diff[1:] <= 0)):
            fires['death_cross'] = 't'
    sma200_now = s200[-1]
    if not np.isnan(sma200_now) and sma200_now > 0:
        if seg[-1] / sma200_now - 1 > 0.30:
            fires['stretched'] = 'q'
    a = _atr_pit(sh, sl, seg, 14)
    if a is not None and seg[-1] > 0 and a / seg[-1] > 0.04:
        fires['high_atr'] = 'q'
    pillars = len(set(fires.values()))
    return (len(fires) >= 3 and pillars >= 2), pillars


def trough_fire(closes, highs, lows, vols, opens, i):
    if i < 220:
        return False, 0
    cs = closes[:i + 1]; hs = highs[:i + 1]; ls = lows[:i + 1]
    vs = vols[:i + 1]; os_ = opens[:i + 1]
    fires = {}
    r = _rsi_pit(cs, 14)
    if r is not None and r < 30:
        fires['rsi_os'] = 't'
    mh, mp = _macd_hist_pit(cs)
    if mh is not None and mp is not None and mp < 0 and mh > 0:
        fires['macd_x'] = 't'
    med = float(np.median(vs[-60:])) if len(vs) >= 60 else 0
    prior_down = sum(1 for j in range(-4, 0) if cs[j] < cs[j - 1])
    if med > 0 and vs[-1] / med > 2.0 and cs[-1] > os_[-1] and prior_down >= 3:
        fires['capit'] = 't'
    s200 = _sma(cs, 200)
    if not np.isnan(s200[-1]) and cs[-1] > s200[-1]:
        for j in range(-11, -1):
            if not np.isnan(s200[j]) and cs[j] < s200[j]:
                fires['reclaim'] = 't'; break
    sma200_now = s200[-1]
    if not np.isnan(sma200_now) and sma200_now > 0:
        if cs[-1] / sma200_now - 1 < -0.15:
            fires['stretch_dn'] = 'q'
    a = _atr_pit(hs, ls, cs, 14)
    if a is not None and cs[-1] > 0 and a / cs[-1] < 0.02:
        fires['low_atr'] = 'q'
    # sharpe-recovery quant
    if len(cs) >= 80:
        rets = np.diff(cs[-61:]) / cs[-61:-1]
        if len(rets) >= 30 and np.std(rets) > 0:
            sharpe = float(np.mean(rets) / np.std(rets))
            high = float(np.max(cs[-120:])) if len(cs) >= 120 else float(np.max(cs))
            dd = cs[-1] / high - 1
            if sharpe > 0 and dd < -0.10:
                fires['sharpe_rec'] = 'q'
    pillars = len(set(fires.values()))
    return (len(fires) >= 3 and pillars >= 2), pillars


# ----------------------------- simulator ------------------------------ #

def _spy_regime_series(spy_closes):
    """Per-bar SPY bull regime. Returns bool array aligned with spy_closes."""
    s200 = _sma(spy_closes, 200)
    n = len(spy_closes)
    out = np.zeros(n, dtype=bool)
    for i in range(n):
        if i < 220 or np.isnan(s200[i]) or np.isnan(s200[i - 20]):
            continue
        win = s200[i - 19:i + 1]
        if np.isnan(win).any():
            continue
        slope = float(np.polyfit(np.arange(20), win, 1)[0])
        out[i] = bool(spy_closes[i] > s200[i] and slope > 0)
    return out


def _align_spy_regime(symbol_idx, spy_df, spy_regime):
    """Return bool array len(symbol_idx): SPY bull regime aligned by date."""
    spy_map = dict(zip(spy_df.index, spy_regime))
    return np.array([spy_map.get(d, False) for d in symbol_idx], dtype=bool)


def _dyn_trail_frac(atr_pct):
    """ATR-based trail in fraction (e.g. 0.10). max(10%, 2.5*ATR%) capped at 15%."""
    if atr_pct is None:
        return 0.10
    return max(0.10, min(0.15, 0.025 * atr_pct))


def simulate(symbol, days=365, version='v3.1', spy_df=None, spy_regime=None):
    df = df_mod.fetch_ohlcv(symbol, days=days + 320)
    if df is None:
        return None
    closes = df['Close'].values.flatten()
    highs = df['High'].values.flatten()
    lows = df['Low'].values.flatten()
    vols = df['Volume'].values.flatten()
    opens = df['Open'].values.flatten()
    idx = df.index
    n = len(closes)
    start_i = max(220, n - days)
    if start_i >= n - 1:
        return None

    # Per-bar SPY bull regime aligned to this symbol's dates
    if version == 'v3.1' and spy_df is not None and spy_regime is not None:
        bull_arr = _align_spy_regime(idx, spy_df, spy_regime)
    else:
        bull_arr = np.zeros(n, dtype=bool)

    entry_price = float(closes[start_i])
    shares = INITIAL / entry_price  # core
    cash = 0.0
    trail_peak = None
    trail_active = False
    trail_frac = 0.07  # v3 default; v3.1 sets dynamically on fire
    last_mt = -COOLDOWN
    last_st = -COOLDOWN
    last_tr = -COOLDOWN
    events = []

    bh_shares = INITIAL / entry_price  # buy & hold reference

    for i in range(start_i + 1, n):
        price = float(closes[i])

        # active trailing stop from a momentum_trim
        if trail_active and shares > 0:
            if trail_peak is None or price > trail_peak:
                trail_peak = price
            if price < trail_peak * (1 - trail_frac):
                cash += shares * price
                events.append((i, f'trail_stop@{trail_frac*100:.1f}%', shares, price))
                shares = 0.0
                trail_active = False

        # secular top: trim 50% or 75%
        if i - last_st >= COOLDOWN:
            fired, pillars = secular_fire(closes, highs, lows, idx, i)
            if fired and shares > 0:
                pct = 0.75 if pillars >= 3 else 0.50
                sell = shares * pct
                cash += sell * price
                shares -= sell
                events.append((i, f'secular_trim_{int(pct*100)}', sell, price))
                last_st = i

        # momentum trim: 30% + activate trail (version-aware)
        if i - last_mt >= COOLDOWN:
            if version == 'v3':
                fired, _, atr_pct = momentum_fire(closes, highs, lows, vols, opens, i, min_pillars=2)
            else:  # v3.1
                req = 4 if bull_arr[i] else 3
                fired, _, atr_pct = momentum_fire(closes, highs, lows, vols, opens, i, min_pillars=req)
            if fired and shares > 0:
                sell = shares * 0.30
                cash += sell * price
                shares -= sell
                trail_active = True
                trail_peak = price
                if version == 'v3':
                    trail_frac = 0.07
                else:
                    trail_frac = _dyn_trail_frac(atr_pct)
                events.append((i, f'mt_trim_30(trail{trail_frac*100:.1f}%)', sell, price))
                last_mt = i

        # trough: add 15% or 20% of original $10K (deploy fresh capital)
        if i - last_tr >= COOLDOWN:
            fired, pillars = trough_fire(closes, highs, lows, vols, opens, i)
            if fired:
                pct = 0.20 if pillars >= 3 else 0.15
                buy_dollars = INITIAL * pct
                add_sh = buy_dollars / price
                shares += add_sh
                cash -= buy_dollars  # cash goes negative to represent out-of-pocket add
                events.append((i, f'trough_add_{int(pct*100)}', add_sh, price))
                last_tr = i

    last_close = float(closes[-1])
    scale_out_value = cash + shares * last_close
    bh_value = bh_shares * last_close
    return {
        'symbol': symbol,
        'version': version,
        'start_price': round(entry_price, 2),
        'end_price': round(last_close, 2),
        'bars': n - start_i,
        'n_events': len(events),
        'events': events[:20],
        'scale_out_pnl': round(scale_out_value - INITIAL, 2),
        'scale_out_ret_pct': round((scale_out_value - INITIAL) / INITIAL * 100, 2),
        'bh_pnl': round(bh_value - INITIAL, 2),
        'bh_ret_pct': round((bh_value - INITIAL) / INITIAL * 100, 2),
        'edge_pct': round(((scale_out_value - bh_value) / INITIAL) * 100, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='+', required=True)
    ap.add_argument('--days', type=int, default=365)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--version', default='v3.1', choices=['v3', 'v3.1'])
    ap.add_argument('--compare', action='store_true', help='Run both v3 and v3.1 side by side')
    args = ap.parse_args()

    # Prefetch SPY for regime
    spy_df = df_mod.fetch_ohlcv('SPY', days=args.days + 320)
    spy_regime = None
    if spy_df is not None:
        spy_regime = _spy_regime_series(spy_df['Close'].values.flatten())

    versions = ['v3', 'v3.1'] if args.compare else [args.version]
    all_rows = {v: [] for v in versions}
    for s in args.symbols:
        print(f"backtest {s}...", file=sys.stderr)
        for v in versions:
            try:
                r = simulate(s.upper(), args.days, version=v, spy_df=spy_df, spy_regime=spy_regime)
            except (ValueError, KeyError, AttributeError, IndexError) as e:
                print(f"[{s}/{v}] {e}", file=sys.stderr); continue
            if r:
                all_rows[v].append(r)

    if args.json:
        print(json.dumps(all_rows, indent=2, default=str))
        return

    if args.compare:
        v3map = {r['symbol']: r for r in all_rows['v3']}
        v31map = {r['symbol']: r for r in all_rows['v3.1']}
        syms = [s.upper() for s in args.symbols if s.upper() in v3map and s.upper() in v31map]
        hdr = f"{'sym':<6}{'v3 $':>10}{'v3 ev':>6}{'v3.1 $':>11}{'v3.1 ev':>8}{'B&H $':>10}{'Δ v3.1-v3':>11}{'edge v3.1':>11}"
        print(hdr); print('-' * len(hdr))
        tot_v3 = tot_v31 = tot_bh = 0.0
        for s in syms:
            a, b = v3map[s], v31map[s]
            delta = b['scale_out_pnl'] - a['scale_out_pnl']
            print(f"{s:<6}{a['scale_out_pnl']:>10.0f}{a['n_events']:>6}"
                  f"{b['scale_out_pnl']:>11.0f}{b['n_events']:>8}"
                  f"{b['bh_pnl']:>10.0f}{delta:>+11.0f}{b['edge_pct']:>+10.2f}%")
            tot_v3 += a['scale_out_pnl']; tot_v31 += b['scale_out_pnl']; tot_bh += b['bh_pnl']
        print('-' * len(hdr))
        n = len(syms) or 1
        invested = INITIAL * n
        print(f"{'TOTAL':<6}{tot_v3:>10.0f}{'':>6}{tot_v31:>11.0f}{'':>8}{tot_bh:>10.0f}"
              f"{tot_v31-tot_v3:>+11.0f}{(tot_v31-tot_bh)/invested*100:>+10.2f}%")
        print(f"\nPortfolio: v3=${INITIAL*n + tot_v3:,.0f}  v3.1=${INITIAL*n + tot_v31:,.0f}  B&H=${INITIAL*n + tot_bh:,.0f}")
        print(f"Edge v3   : {(tot_v3-tot_bh)/invested*100:+.2f}%")
        print(f"Edge v3.1 : {(tot_v31-tot_bh)/invested*100:+.2f}%")
        return

    rows = all_rows[versions[0]]
    hdr = f"{'sym':<6}{'bars':>5}{'events':>7}{'scale$':>10}{'scale%':>9}{'bh$':>10}{'bh%':>9}{'edge%':>9}"
    print(hdr)
    print('-' * len(hdr))
    tot_so = tot_bh = 0.0
    for r in rows:
        print(f"{r['symbol']:<6}{r['bars']:>5}{r['n_events']:>7}"
              f"{r['scale_out_pnl']:>10.2f}{r['scale_out_ret_pct']:>8.2f}%"
              f"{r['bh_pnl']:>10.2f}{r['bh_ret_pct']:>8.2f}%"
              f"{r['edge_pct']:>8.2f}%")
        tot_so += r['scale_out_pnl']; tot_bh += r['bh_pnl']
    print('-' * len(hdr))
    n = len(rows) or 1
    invested = INITIAL * n
    print(f"{'TOTAL':<6}{'':>5}{'':>7}{tot_so:>10.2f}{tot_so/invested*100:>8.2f}%"
          f"{tot_bh:>10.2f}{tot_bh/invested*100:>8.2f}%"
          f"{(tot_so-tot_bh)/invested*100:>8.2f}%")


if __name__ == '__main__':
    main()
