"""
Options engine API — serves chains+Greeks and formulated strategies to the dashboard.
Thin wrappers over the options_cli package (yfinance chains + Black-Scholes Greeks +
vertical-spread formulation). Sync handlers so FastAPI runs the slow yfinance fetches
in its threadpool instead of blocking the event loop.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from options_cli.chains import get_chain
from options_cli.strategies import build_verticals, build_income

options_router = APIRouter(prefix="/api/options", tags=["options"])
logger = logging.getLogger("options_routes")


def _contract_json(c) -> Dict[str, Any]:
    g = c.greeks
    return {
        "strike": c.strike, "kind": c.kind, "bid": c.bid, "ask": c.ask, "mid": c.mid,
        "last": c.last, "volume": c.volume, "open_interest": c.open_interest,
        "iv": round(c.iv, 4), "dte": c.dte,
        "delta": round(g.delta, 3), "gamma": round(g.gamma, 4), "theta": round(g.theta, 3),
        "vega": round(g.vega, 3), "prob_itm": round(g.prob_itm, 3),
    }


@options_router.get("/{symbol}/expirations")
def expirations(symbol: str) -> Dict[str, Any]:
    ch = get_chain(symbol, max_exps=1)
    if not ch.expirations:
        raise HTTPException(404, f"no options for {symbol.upper()}")
    return {"symbol": ch.symbol, "spot": ch.spot, "expirations": ch.expirations}


@options_router.get("/{symbol}/chain")
def chain(symbol: str, exp: Optional[str] = None, target_dte: int = 30) -> Dict[str, Any]:
    ch = get_chain(symbol, expirations=[exp] if exp else None, max_exps=1,
                   target_dte=None if exp else target_dte)
    if not ch.contracts:
        raise HTTPException(404, f"no options for {symbol.upper()}")
    use = ch.contracts[0].expiration if not exp else exp
    calls = sorted(ch.for_exp(use, "call"), key=lambda c: c.strike)
    puts = sorted(ch.for_exp(use, "put"), key=lambda c: c.strike)
    return {
        "symbol": ch.symbol, "spot": ch.spot, "rate": ch.rate,
        "expiration": use, "expirations": ch.expirations,
        "calls": [_contract_json(c) for c in calls],
        "puts": [_contract_json(c) for c in puts],
    }


@options_router.get("/{symbol}/strategies")
def strategies(
    symbol: str,
    kind: str = Query("call", pattern="^(call|put)$"),
    direction: str = Query("bull", pattern="^(bull|bear)$"),
    exp: Optional[str] = None,
    width: float = 0.0,
    top: int = 12,
    min_oi: int = 25,
    target_dte: int = 30,
) -> Dict[str, Any]:
    ch = get_chain(symbol, expirations=[exp] if exp else None, max_exps=1,
                   target_dte=None if exp else target_dte)
    use = (exp or (ch.contracts[0].expiration if ch.contracts else None))
    if not use:
        raise HTTPException(404, f"no options for {symbol.upper()}")
    verts = build_verticals(ch, use, kind, direction, max_width=width, min_oi=min_oi)
    out: List[Dict[str, Any]] = []
    for v in verts[:top]:
        out.append({
            "label": v.label, "kind": v.kind, "direction": v.direction,
            "debit_credit": v.debit_credit, "net": v.net,
            "long_strike": v.long.strike, "short_strike": v.short.strike,
            "width": v.width, "max_profit": v.max_profit, "max_loss": v.max_loss,
            "breakeven": v.breakeven, "rr": v.rr, "pop": v.pop, "score": v.score,
        })
    return {"symbol": ch.symbol, "spot": ch.spot, "expiration": use,
            "kind": kind, "direction": direction, "strategies": out}


@options_router.get("/{symbol}/income")
def income(
    symbol: str,
    kind: str = Query("put", pattern="^(put|call)$"),  # put=cash-secured put, call=covered call
    exp: Optional[str] = None,
    top: int = 12,
    min_oi: int = 25,
    target_dte: int = 30,
) -> Dict[str, Any]:
    ch = get_chain(symbol, expirations=[exp] if exp else None, max_exps=1,
                   target_dte=None if exp else target_dte)
    use = (exp or (ch.contracts[0].expiration if ch.contracts else None))
    if not use:
        raise HTTPException(404, f"no options for {symbol.upper()}")
    trades = build_income(ch, use, kind, min_oi=min_oi)
    out = [{
        "label": t.label, "type": t.type, "strike": t.strike, "premium": t.premium,
        "breakeven": t.breakeven, "max_profit": t.max_profit, "pop": t.pop,
        "annual_yield": t.annual_yield, "cushion": t.cushion, "capital": t.capital,
        "delta": t.delta, "theta": t.theta, "dte": t.dte, "score": t.score,
    } for t in trades[:top]]
    return {"symbol": ch.symbol, "spot": ch.spot, "expiration": use, "kind": kind, "income": out}
