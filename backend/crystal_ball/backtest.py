"""
Crystal Ball backtesting engine — institutional discipline, honest stats.

The single most important guard here is **no look-ahead**. A backtester that
peeks at the future is worse than useless — it manufactures edge that won't
survive contact with a live market, which is the exact snake-oil failure mode
this whole tab exists to avoid. So the contract is strict and enforced by
construction:

    The signal for the decision made at the close of bar ``i`` is computed from
    ``series[: i + 1]`` ONLY. The trade it opens fills at the close of bar ``i``
    (with costs), and its outcome is read from bars ``i+1 ...`` — never earlier.

The engine is generic: it takes a ``signal_fn(close_window, volume_window) ->
{direction, prob, confidence}`` so it can evaluate ANY strategy, not just Crystal
Ball. ``crystal_ball_signal_fn`` adapts the reversal engine to that contract.

What it computes
----------------
- A bar-level mark-to-market equity curve (position is held between entry/exit),
  so Sharpe / Sortino / drawdown are measured on daily P&L, not just per-trade.
- Institutional stats: total return, CAGR, Sharpe, Sortino, max drawdown,
  Calmar, win rate, profit factor, avg win/loss, expectancy, exposure, # trades.
- A buy & hold benchmark over the identical window.
- Predictor-specific honesty metrics: directional hit-rate of the signal and a
  calibration (Brier) read — does "65% confidence" actually win ~65% of the time?

Costs: ``cost_bps`` (commission) + ``slippage_bps`` are charged per side on every
entry and exit. Defaults are deliberately non-zero — a frictionless backtest is a
lie.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np

from .fusion import crystal_ball_read

_CONF_RANK = {"low": 0, "medium": 1, "high": 2}
_TRADING_DAYS = 252.0


# ---------------------------------------------------------------------------
# Signal adapter
# ---------------------------------------------------------------------------

def crystal_ball_signal_fn(close_window: np.ndarray,
                           volume_window: Optional[np.ndarray]) -> Dict[str, Any]:
    """Adapt ``crystal_ball_read`` to the backtester's signal contract.

    Returns ``{direction, prob, confidence}``. The read is computed on the
    supplied window only (the caller guarantees it ends at the decision bar), so
    there is no look-ahead.
    """
    r = crystal_ball_read("BT", close_window, volume=volume_window)
    return {
        "direction": r["direction"],
        "prob": r["reversal_probability"],
        "confidence": r["confidence"],
    }


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run_backtest(
    close,
    signal_fn: Callable[[np.ndarray, Optional[np.ndarray]], Dict[str, Any]] = crystal_ball_signal_fn,
    *,
    volume=None,
    dates: Optional[List[Any]] = None,
    horizon: int = 10,
    prob_threshold: float = 0.55,
    min_confidence: str = "medium",
    cost_bps: float = 5.0,
    slippage_bps: float = 5.0,
    warmup: int = 120,
    allow_long: bool = True,
    allow_short: bool = True,
    max_eval_bars: int = 600,
) -> Dict[str, Any]:
    """Walk-forward backtest of ``signal_fn`` on a price series.

    Strategy semantics (single position, sequential trades):
      - At each bar ``i`` (no open position), evaluate the signal on ``close[:i+1]``.
      - A "bottom" reversal call -> go LONG; a "top" call -> go SHORT (if enabled),
        provided ``prob >= prob_threshold`` and ``confidence >= min_confidence``.
      - The position is held until ``horizon`` bars pass OR the invalidation rule
        trips (a close beyond the entry-window extreme), whichever comes first.
      - Costs (commission + slippage) are charged per side on entry and exit.

    Returns a JSON-ready dict: ``{ok, stats, benchmark, trades, equity_curve,
    calibration, params, n_bars}``. On too-little data: ``{ok: False, reason}``.
    """
    c = np.asarray(close, dtype=float).ravel()
    mask = np.isfinite(c)
    c = c[mask]
    v = None
    if volume is not None:
        v = np.asarray(volume, dtype=float).ravel()
        v = v[mask] if v.size == mask.size else None
    n = c.size
    if n < warmup + horizon + 5:
        return {"ok": False, "reason": f"need >= {warmup + horizon + 5} bars, got {n}"}

    # Bound the evaluation window for cost: only walk the most recent
    # ``max_eval_bars`` decision points (warmup still uses all prior data).
    start = max(warmup, n - max_eval_bars)
    per_side_cost = (cost_bps + slippage_bps) / 10000.0
    min_rank = _CONF_RANK.get(min_confidence, 1)

    # Bar-level strategy return series (position held i->i+1 earns that bar's move).
    pos = np.zeros(n, dtype=float)          # position active OVER bar t (t-1 -> t)
    cost_bar = np.zeros(n, dtype=float)     # cost charged AT bar t
    trades: List[Dict[str, Any]] = []

    i = start
    last_exit = -1
    while i < n - 1:
        window = c[: i + 1]
        vol_window = v[: i + 1] if v is not None else None
        try:
            sig = signal_fn(window, vol_window)
        except Exception:  # noqa: BLE001 — a bad bar must not poison the run
            i += 1
            continue

        direction = sig.get("direction", "none")
        prob = float(sig.get("prob", 0.0) or 0.0)
        conf = sig.get("confidence", "low")
        fire = (
            direction in ("top", "bottom")
            and prob >= prob_threshold
            and _CONF_RANK.get(conf, 0) >= min_rank
            and ((direction == "bottom" and allow_long) or (direction == "top" and allow_short))
        )
        if not fire:
            i += 1
            continue

        side = 1.0 if direction == "bottom" else -1.0  # long on bottom, short on top
        entry_i = i
        entry_px = c[entry_i]
        # Invalidation extreme over the trailing 20-bar entry window.
        win = c[max(0, entry_i - 19): entry_i + 1]
        inval = float(np.max(win)) if side < 0 else float(np.min(win))

        # Hold forward up to `horizon`, exit early on invalidation breach.
        exit_i = min(entry_i + horizon, n - 1)
        for j in range(entry_i + 1, min(entry_i + horizon, n - 1) + 1):
            if side < 0 and c[j] > inval:      # short invalidated: close above extreme
                exit_i = j
                break
            if side > 0 and c[j] < inval:      # long invalidated: close below extreme
                exit_i = j
                break
            exit_i = j

        # Mark position over each held bar (entry+1 .. exit earns that bar's move).
        for t in range(entry_i + 1, exit_i + 1):
            pos[t] = side
        cost_bar[entry_i] += per_side_cost     # entry friction
        cost_bar[exit_i] += per_side_cost      # exit friction

        exit_px = c[exit_i]
        gross = side * (exit_px / entry_px - 1.0)
        net = gross - 2.0 * per_side_cost
        trades.append({
            "entry_idx": int(entry_i),
            "exit_idx": int(exit_i),
            "side": "long" if side > 0 else "short",
            "direction": direction,
            "prob": round(prob, 3),
            "confidence": conf,
            "entry_px": round(float(entry_px), 4),
            "exit_px": round(float(exit_px), 4),
            "bars_held": int(exit_i - entry_i),
            "gross_return": round(float(gross), 5),
            "net_return": round(float(net), 5),
            "entry_date": _date_at(dates, entry_i),
            "exit_date": _date_at(dates, exit_i),
        })
        last_exit = exit_i
        i = exit_i + 1  # sequential: no overlapping positions

    # --- Bar-level P&L -> equity curve ------------------------------------
    bar_ret = np.zeros(n, dtype=float)
    px_ret = np.zeros(n, dtype=float)
    px_ret[1:] = c[1:] / c[:-1] - 1.0
    bar_ret = pos * px_ret - cost_bar
    # Only the evaluated region contributes to stats.
    seg = slice(start, n)
    strat_r = bar_ret[seg]
    bench_r = px_ret[seg]
    equity = np.cumprod(1.0 + strat_r)
    bench_eq = np.cumprod(1.0 + bench_r)

    stats = _perf_stats(strat_r, equity, trades, pos[seg])
    benchmark = _perf_stats(bench_r, bench_eq, [], np.ones_like(bench_r))
    benchmark = {k: benchmark[k] for k in ("total_return", "cagr", "sharpe", "max_drawdown")}

    calibration = _calibration_from_trades(trades)
    equity_curve = _equity_points(equity, dates, start)

    return {
        "ok": True,
        "n_bars": int(n),
        "eval_bars": int(n - start),
        "params": {
            "horizon": horizon, "prob_threshold": prob_threshold,
            "min_confidence": min_confidence, "cost_bps": cost_bps,
            "slippage_bps": slippage_bps, "allow_long": allow_long,
            "allow_short": allow_short,
        },
        "stats": stats,
        "benchmark": benchmark,
        "calibration": calibration,
        "trades": trades,
        "equity_curve": equity_curve,
    }


# ---------------------------------------------------------------------------
# stats helpers
# ---------------------------------------------------------------------------

def _perf_stats(rets: np.ndarray, equity: np.ndarray, trades: List[Dict[str, Any]],
                pos: np.ndarray) -> Dict[str, Any]:
    rets = np.asarray(rets, dtype=float)
    if rets.size == 0 or equity.size == 0:
        return _empty_stats()
    total_return = float(equity[-1] - 1.0)
    years = max(1e-9, rets.size / _TRADING_DAYS)
    cagr = float((equity[-1]) ** (1.0 / years) - 1.0) if equity[-1] > 0 else -1.0

    mu = float(np.mean(rets))
    sd = float(np.std(rets, ddof=1)) if rets.size > 1 else 0.0
    sharpe = float(mu / sd * np.sqrt(_TRADING_DAYS)) if sd > 0 else 0.0
    downside = rets[rets < 0]
    dd_sd = float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
    sortino = float(mu / dd_sd * np.sqrt(_TRADING_DAYS)) if dd_sd > 0 else 0.0

    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0
    max_dd = float(np.min(drawdown)) if drawdown.size else 0.0
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    exposure = float(np.mean(np.abs(pos) > 0)) if pos.size else 0.0

    out = {
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(calmar, 3),
        "exposure": round(exposure, 3),
        "volatility_ann": round(sd * np.sqrt(_TRADING_DAYS), 4),
    }
    out.update(_trade_stats(trades))
    return out


def _trade_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "win_rate": None, "profit_factor": None,
                "avg_win": None, "avg_loss": None, "expectancy": None, "avg_bars_held": None}
    nets = np.array([t["net_return"] for t in trades], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    gross_win = float(np.sum(wins))
    gross_loss = float(-np.sum(losses))
    return {
        "n_trades": n,
        "win_rate": round(float(wins.size / n), 3),
        "profit_factor": round(float(gross_win / gross_loss), 3) if gross_loss > 0 else None,
        "avg_win": round(float(np.mean(wins)), 4) if wins.size else 0.0,
        "avg_loss": round(float(np.mean(losses)), 4) if losses.size else 0.0,
        "expectancy": round(float(np.mean(nets)), 4),
        "avg_bars_held": round(float(np.mean([t["bars_held"] for t in trades])), 1),
    }


def _calibration_from_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Brier score + reliability buckets over the backtest's own predictions.

    Outcome = 1 if the trade was profitable (the predicted reversal direction
    paid), else 0. Compares the model's stated probability against realized
    win frequency — the core 'is it calibrated?' test.
    """
    if not trades:
        return {"brier": None, "n": 0, "buckets": []}
    probs = np.array([t["prob"] for t in trades], dtype=float)
    outcomes = np.array([1.0 if t["net_return"] > 0 else 0.0 for t in trades], dtype=float)
    brier = float(np.mean((probs - outcomes) ** 2))
    edges = [0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    buckets = []
    lo = 0.5
    for hi in edges:
        m = (probs >= lo) & (probs < hi)
        if m.any():
            buckets.append({
                "range": f"{lo:.2f}-{min(hi,1.0):.2f}",
                "n": int(m.sum()),
                "predicted": round(float(np.mean(probs[m])), 3),
                "realized": round(float(np.mean(outcomes[m])), 3),
            })
        lo = hi
    return {"brier": round(brier, 4), "n": len(trades), "buckets": buckets}


def _equity_points(equity: np.ndarray, dates: Optional[List[Any]], start: int) -> List[Dict[str, Any]]:
    pts = []
    for k, val in enumerate(equity):
        d = _date_at(dates, start + k)
        pts.append({"t": d if d is not None else int(start + k), "equity": round(float(val), 5)})
    return pts


def _date_at(dates: Optional[List[Any]], idx: int) -> Optional[str]:
    if not dates or idx < 0 or idx >= len(dates):
        return None
    try:
        return str(dates[idx])[:10]
    except Exception:  # noqa: BLE001
        return None


def _empty_stats() -> Dict[str, Any]:
    return {
        "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0,
        "max_drawdown": 0.0, "calmar": 0.0, "exposure": 0.0, "volatility_ann": 0.0,
        "n_trades": 0, "win_rate": None, "profit_factor": None,
        "avg_win": None, "avg_loss": None, "expectancy": None, "avg_bars_held": None,
    }
