"""
The Wheel — a guided income loop. Sell a cash-secured put on a stock you'd own;
if assigned, sell covered calls against the shares; if called away, back to the put.

`wheel_status()` figures out WHICH phase you're in for a ticker (do you hold ≥100
shares?) and suggests the next trade with concrete strikes. Zero-token.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

from .chains import get_chain
from .strategies import build_income, IncomeTrade

logger = logging.getLogger("options_cli.wheel")
BACKEND = os.getenv("CRACKDAWN_BACKEND_URL", "http://localhost:8000")

STEPS = [
    ("sell_put", "Sell a cash-secured put on a stock you'd happily own."),
    ("put_outcome", "Expires above strike → keep the premium, repeat. Below → you're assigned 100 shares at the strike."),
    ("sell_call", "Now you own shares: sell a covered call against them."),
    ("call_outcome", "Expires below strike → keep premium + shares, repeat. Above → shares called away, back to step 1."),
]


def shares_held(symbol: str) -> float:
    """Equity (not option) shares of `symbol` in the book."""
    try:
        r = requests.get(f"{BACKEND}/api/portfolio/positions", timeout=25)
        r.raise_for_status()
        d = r.json()
        rows = d if isinstance(d, list) else d.get("positions") or d.get("holdings") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("positions fetch failed: %s", e)
        return 0.0
    total = 0.0
    for p in rows:
        sym = str(p.get("symbol") or "").upper().strip()
        kind = str(p.get("type") or "").lower()
        if sym == symbol.upper() and "option" not in kind and len(sym) <= 6:
            total += float(p.get("quantity") or 0.0)
    return total


def wheel_status(symbol: str, target_dte: int = 30) -> Dict[str, Any]:
    symbol = symbol.upper()
    held = shares_held(symbol)
    phase = "covered_call" if held >= 100 else "cash_secured_put"
    kind = "call" if phase == "covered_call" else "put"
    ch = get_chain(symbol, target_dte=target_dte)
    if not ch.contracts:
        return {"symbol": symbol, "error": "no options"}
    exp = ch.contracts[0].expiration
    suggestions: List[IncomeTrade] = build_income(ch, exp, kind)[:3]
    step = "sell_call" if phase == "covered_call" else "sell_put"
    return {
        "symbol": symbol, "spot": ch.spot, "expiration": exp,
        "shares_held": held, "phase": phase, "current_step": step,
        "next_move": ("Sell a covered call against your shares to collect premium."
                      if phase == "covered_call"
                      else "Sell a cash-secured put — get paid to potentially buy the shares lower."),
        "suggestions": [{
            "strike": t.strike, "premium": t.premium, "breakeven": t.breakeven,
            "pop": t.pop, "annual_yield": t.annual_yield, "cushion": t.cushion, "dte": t.dte,
        } for t in suggestions],
        "steps": [{"id": s[0], "text": s[1]} for s in STEPS],
    }
