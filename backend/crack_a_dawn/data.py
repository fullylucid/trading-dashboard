"""
Crack-a-Dawn — data gather (P0, zero-token).

Builds MoverInput rows from yfinance: the prior-close -> current move, the ~30d
return baseline (for sigma), volume (for RVOL), and the market move + beta (for the
beta-residual). yfinance is the source because it carries pre/post-market; on the
real 6am run we read the pre-market last, off-hours/weekend we fall back to the most
recent regular close so the pipeline is always exercisable.

Network + parsing is per-ticker fault-isolated (a dead ticker drops to None, never
kills the sweep) — same discipline as the scanner overhaul.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from .scoring import MoverInput

logger = logging.getLogger("crack_a_dawn.data")

MARKET_PROXY = "SPY"
_HIST_DAYS = 45  # calendar days to safely cover ~30 trading days


def _pct_returns(closes: Sequence[float]) -> List[float]:
    out: List[float] = []
    for a, b in zip(closes, closes[1:]):
        if a:
            out.append((b - a) / a * 100.0)
    return out


def _fetch_one(yf, ticker: str, prepost: bool):
    """Return dict(move_pct, returns[], last_vol, avg_vol, last) or None."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=f"{_HIST_DAYS}d", interval="1d", prepost=False)
        if hist is None or hist.empty or len(hist) < 5:
            logger.warning("no history for %s", ticker)
            return None
        closes = [float(c) for c in hist["Close"].tolist() if c == c]
        vols = [float(v) for v in hist["Volume"].tolist() if v == v]
        prev_close = closes[-1]                      # most recent regular close
        returns = _pct_returns(closes)               # ~30 daily % returns

        # current price: pre/post last if available, else the latest close.
        last = prev_close
        if prepost:
            try:
                fi = t.fast_info
                last = float(getattr(fi, "last_price", None) or prev_close)
            except Exception:
                pass
        # off-hours: use the most recent realized daily move so the pipeline is testable
        if abs(last - prev_close) < 1e-9 and len(closes) >= 2:
            prev_close = closes[-2]
            last = closes[-1]

        move_pct = (last - prev_close) / prev_close * 100.0 if prev_close else 0.0
        avg_vol = sum(vols[-20:]) / max(len(vols[-20:]), 1) if vols else None
        last_vol = vols[-1] if vols else None
        return {"move_pct": move_pct, "returns": returns,
                "last_vol": last_vol, "avg_vol": avg_vol, "last": last}
    except Exception as e:  # noqa: BLE001 — fault-isolate per ticker
        logger.warning("fetch failed for %s: %s", ticker, e)
        return None


def _beta(asset_returns: Sequence[float], market_returns: Sequence[float]) -> float:
    n = min(len(asset_returns), len(market_returns))
    if n < 5:
        return 1.0
    a, m = asset_returns[-n:], market_returns[-n:]
    mbar = sum(m) / n
    var = sum((x - mbar) ** 2 for x in m) / n
    if var <= 0:
        return 1.0
    abar = sum(a) / n
    cov = sum((a[i] - abar) * (m[i] - mbar) for i in range(n)) / n
    return cov / var


def build_inputs(
    tickers: Sequence[str],
    held: Optional[Dict[str, float]] = None,  # ticker -> weight (0..1) for holdings
    prepost: bool = True,
) -> List[MoverInput]:
    """Fetch and assemble MoverInput rows. `held` maps holding tickers to book weight."""
    import yfinance as yf  # imported lazily so unit tests need no network/deps

    held = held or {}
    market = _fetch_one(yf, MARKET_PROXY, prepost)
    mkt_move = market["move_pct"] if market else 0.0
    mkt_returns = market["returns"] if market else []

    rows: List[MoverInput] = []
    for tk in tickers:
        d = _fetch_one(yf, tk, prepost)
        if not d:
            continue
        rows.append(MoverInput(
            ticker=tk,
            move_pct=d["move_pct"],
            hist_returns=d["returns"],
            market_move_pct=mkt_move,
            beta=_beta(d["returns"], mkt_returns),
            premarket_volume=d["last_vol"],
            avg_volume=d["avg_vol"],
            held=tk in held,
            weight=held.get(tk, 0.0),
            intent="hold" if tk in held else "watch_entry",
        ))
    return rows
