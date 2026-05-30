"""
Opportunity discovery: assemble the candidate universe, compute deterministic
option snapshots, and build the structured prompt handed to Claude on the WSL2
box via the agent bridge.

Universe = your stocks (brokerage positions) + watchlist + a curated market
scan of liquid, optionable names you may not be tracking. The snapshot (spot,
IV, IV-rank proxy, realized vol, expirations with DTE + expected move,
liquidity) is the "Python computes" deliverable; Claude does the ranking and
strategy reasoning on top of it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import chains

logger = logging.getLogger(__name__)

# Curated liquid, optionable names for the "stocks you don't know about" leg of
# discovery. Deep, tight option markets across sectors so the expected-move /
# IV-premium screen is meaningful. Excludes whatever's already in your book.
MARKET_SCAN_UNIVERSE: List[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
    # Semis / AI infra
    "MU", "SMCI", "ARM", "TSM", "QCOM", "INTC",
    # High-IV / retail favorites
    "PLTR", "COIN", "MSTR", "MARA", "SOFI", "RIVN", "AFRM", "DKNG",
    # Index / vol ETFs
    "SPY", "QQQ", "IWM",
    # Financials / energy / industrials
    "JPM", "BAC", "XOM", "CVX", "BA", "CAT", "GE",
    # Consumer / pharma
    "DIS", "NKE", "LLY", "UNH", "COST",
]


async def _portfolio_symbols() -> List[str]:
    """Symbols from connected brokerage positions + watchlist (best-effort)."""
    try:
        from snaptrade_portfolio import get_portfolio_instance
    except Exception:
        return []
    try:
        portfolio = await get_portfolio_instance()
        data = await portfolio.get_portfolio()
    except Exception as e:  # pragma: no cover - depends on live OAuth
        logger.warning("portfolio symbols unavailable: %s", e)
        return []

    syms: List[str] = []
    for pos in (data.get("positions") or []):
        s = pos.get("symbol")
        if isinstance(s, str) and s:
            syms.append(s.upper())
    for w in (data.get("watchlist") or []):
        s = w.get("symbol") if isinstance(w, dict) else w
        if isinstance(s, str) and s:
            syms.append(s.upper())
    return syms


def _watchlist_symbols() -> List[str]:
    """Static high-conviction watches (Hermes MEMORY) so discovery still has a
    'your stocks' anchor even when the brokerage link is offline."""
    return ["SMCI", "CRDO", "GLW", "GFS", "AMD"]


async def build_universe(
    extra_symbols: Optional[List[str]] = None,
    *,
    include_market_scan: bool = True,
    market_scan_limit: int = 20,
) -> Dict[str, List[str]]:
    """Resolve the candidate universe, tagged by source.

    Returns {"holdings": [...], "watchlist": [...], "market_scan": [...]} with
    each symbol appearing under exactly one source (holdings win over watchlist
    win over market scan).
    """
    holdings = await _portfolio_symbols()
    watch = list(dict.fromkeys(_watchlist_symbols() + [s.upper() for s in (extra_symbols or [])]))

    seen = set(holdings)
    watch = [s for s in watch if s not in seen]
    seen.update(watch)

    market: List[str] = []
    if include_market_scan:
        market = [s for s in MARKET_SCAN_UNIVERSE if s not in seen][:market_scan_limit]

    return {
        "holdings": list(dict.fromkeys(holdings)),
        "watchlist": watch,
        "market_scan": market,
    }


async def _snapshot_async(symbol: str, sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        try:
            return await asyncio.wait_for(asyncio.to_thread(chains.get_snapshot, symbol), timeout=25.0)
        except asyncio.TimeoutError:
            return {"symbol": symbol, "error": "timeout"}
        except Exception as e:  # pragma: no cover
            return {"symbol": symbol, "error": str(e)}


def _expirations_in_horizon(snap: Dict[str, Any], horizon_days: float, *, pad: float = 1.5) -> List[Dict[str, Any]]:
    """Expirations near the requested horizon — the timeframe-aware shortlist.

    Keeps expirations from ~40% of the horizon out to `pad`x it, so a 30-day
    view surfaces the ~2-week through ~6-week expirations to trade around.
    """
    exps = snap.get("expirations") or []
    lo = horizon_days * 0.4
    hi = horizon_days * pad
    hits = [e for e in exps if lo <= e.get("dte", 0) <= hi]
    if not hits and exps:
        # Fall back to the single expiration closest to the horizon.
        hits = [min(exps, key=lambda e: abs(e.get("dte", 0) - horizon_days))]
    return hits


async def build_snapshot(
    horizon_days: float,
    *,
    extra_symbols: Optional[List[str]] = None,
    include_market_scan: bool = True,
    concurrency: int = 8,
) -> Dict[str, Any]:
    """Compute the full deterministic opportunity snapshot for the universe.

    Each symbol gets its option snapshot plus the horizon-relevant expirations
    (with DTE + expected move). Symbols that fail to resolve are reported under
    `errors` rather than dropped silently.
    """
    universe = await build_universe(extra_symbols, include_market_scan=include_market_scan)
    by_symbol: Dict[str, str] = {}
    for source, syms in universe.items():
        for s in syms:
            by_symbol.setdefault(s, source)

    all_syms = list(by_symbol.keys())
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*[_snapshot_async(s, sem) for s in all_syms])

    candidates: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for snap in results:
        sym = snap.get("symbol", "?")
        if snap.get("error"):
            errors.append({"symbol": sym, "error": snap["error"]})
            continue
        snap["source"] = by_symbol.get(sym, "unknown")
        snap["horizon_expirations"] = _expirations_in_horizon(snap, horizon_days)
        candidates.append(snap)

    # Rank the market-scan discoveries by how "interesting" the options look:
    # rich IV premium and a meaningful expected move over the horizon.
    def _interest(snap: Dict[str, Any]) -> float:
        prem = snap.get("iv_premium") or 1.0
        hexp = snap.get("horizon_expirations") or []
        move_pct = max((e.get("expected_move_pct") or 0.0) for e in hexp) if hexp else 0.0
        return prem * 1.5 + move_pct * 0.1

    candidates.sort(key=_interest, reverse=True)

    return {
        "horizon_days": horizon_days,
        "universe_counts": {k: len(v) for k, v in universe.items()},
        "candidates": candidates,
        "errors": errors,
        "asof": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

OUTLOOK_HINTS = {
    "bullish": "directional upside; favor call structures, bull spreads, or cash-secured puts on names you'd own",
    "bearish": "directional downside; favor put structures, bear spreads, or protective hedges",
    "neutral": "range-bound; favor premium-selling (iron condors, credit spreads, covered calls) on high IV-rank names",
    "volatile": "a large move of unknown direction; favor long straddles/strangles where IV is cheap into a catalyst",
    "any": "no fixed bias; pick the structure each name's regime is paid to be right about",
}


def build_claude_prompt(snapshot: Dict[str, Any], outlook: str, horizon_days: float, *, top_n: int = 12) -> str:
    """Render the deterministic snapshot into a focused instruction for Claude.

    The numbers are already computed — Claude's job is judgment: pick the best
    names, the specific expiration to trade, and the structure that fits each
    one's IV regime, then explain the thesis and the risk.
    """
    outlook = (outlook or "any").lower()
    hint = OUTLOOK_HINTS.get(outlook, OUTLOOK_HINTS["any"])
    candidates = (snapshot.get("candidates") or [])[:top_n]

    lines: List[str] = []
    lines.append("# Options opportunity scan")
    lines.append("")
    lines.append(
        f"You are screening for options opportunities over roughly a **{int(horizon_days)}-day** horizon. "
        f"My outlook is **{outlook}** — {hint}."
    )
    lines.append("")
    lines.append(
        "The market data below was computed deterministically (yfinance + Black-Scholes): spot, "
        "ATM implied vol, an IV-rank *proxy* (0-100, where it sits vs realized vol), the IV/realized "
        "premium, and the expirations that fall in my horizon with their days-to-expiry and ±1σ expected move. "
        "Treat these numbers as given."
    )
    lines.append("")
    lines.append("## Candidates")
    for c in candidates:
        src = c.get("source", "?")
        ivr = c.get("iv_rank_proxy")
        prem = c.get("iv_premium")
        hexp = c.get("horizon_expirations") or []
        exp_str = ", ".join(
            f"{e['date']} ({int(e['dte'])}d, ±{e.get('expected_move_pct', '?')}%)" for e in hexp
        ) or "no expirations in horizon"
        lines.append(
            f"- **{c['symbol']}** [{src}] — spot ${c.get('spot')}, "
            f"ATM IV {_pct(c.get('atm_iv'))}, IV-rank≈{ivr if ivr is not None else '?'}, "
            f"IV/realized {prem if prem is not None else '?'}x. Expirations: {exp_str}"
        )
    lines.append("")
    lines.append("## What to return")
    lines.append(
        "Pick the 3-6 best opportunities. For each, give: ticker; the specific expiration date to trade and why "
        "that timeframe; the exact strategy and strikes (relative to spot/expected move); whether IV rank argues "
        "for buying or selling premium; the net debit/credit, max profit, max loss and breakeven; the directional "
        "thesis; and the single biggest risk. Prefer defined-risk structures unless an undefined-risk play is "
        "clearly superior, and say so. Rank them best-first. End with one line on anything you'd skip and why. "
        "Educational only — not investment advice."
    )
    return "\n".join(lines)


def _pct(x: Optional[float]) -> str:
    return f"{round(100 * x)}%" if isinstance(x, (int, float)) and x else "?"
