"""
2Chainz — live portfolio pull (zero-token). Shared by: the chat agent's context, and
the scheduled open/close snapshots. Day P&L uses Finnhub prev-close (free, fast).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

logger = logging.getLogger("twochainz.portfolio")
BACKEND = os.getenv("CRACKDAWN_BACKEND_URL", "http://localhost:8000")
FINNHUB = "https://finnhub.io/api/v1"


def _positions() -> List[Dict[str, Any]]:
    try:
        r = requests.get(f"{BACKEND}/api/portfolio/positions", timeout=25)
        r.raise_for_status()
        d = r.json()
        return d if isinstance(d, list) else d.get("positions") or d.get("holdings") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("positions fetch failed: %s", e)
        return []


def _prev_close(sym: str) -> float:
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return 0.0
    try:
        q = requests.get(f"{FINNHUB}/quote", params={"symbol": sym, "token": key}, timeout=8).json()
        return float(q.get("pc") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def snapshot() -> Dict[str, Any]:
    """Aggregated live book with day P&L. Returns dict(total, holdings[...])."""
    agg: Dict[str, Dict[str, float]] = {}
    for p in _positions():
        sym = (p.get("symbol") or "").upper().strip()
        if not sym:
            continue
        a = agg.setdefault(sym, {"qty": 0.0, "value": 0.0, "cur": 0.0, "upl": 0.0})
        a["qty"] += float(p.get("quantity") or 0.0)
        a["value"] += float(p.get("current_value") or p.get("market_value") or 0.0)
        a["cur"] = float(p.get("current_price") or p.get("last_trade_price") or a["cur"])
        a["upl"] += float(p.get("unrealized_pl") or p.get("gain_loss") or 0.0)

    total_val = sum(a["value"] for a in agg.values())
    holdings = []
    day_total = 0.0
    for sym, a in agg.items():
        pc = _prev_close(sym)
        day_pl = (a["cur"] - pc) * a["qty"] if pc else 0.0
        day_pct = (a["cur"] - pc) / pc * 100.0 if pc else 0.0
        day_total += day_pl
        holdings.append({
            "symbol": sym, "value": a["value"],
            "weight": a["value"] / total_val if total_val else 0.0,
            "day_pl": day_pl, "day_pct": day_pct, "unrealized_pl": a["upl"],
        })
    holdings.sort(key=lambda h: h["value"], reverse=True)
    return {"total_value": total_val, "day_pl": day_total, "holdings": holdings}


def format_text(snap: Dict[str, Any], header: str, top: int = 12) -> str:
    tv = snap["total_value"]
    dp = snap["day_pl"]
    dpct = (dp / (tv - dp) * 100.0) if (tv - dp) else 0.0
    arrow = "🟢" if dp >= 0 else "🔴"
    lines = [f"*{header}*",
             f"💼 Book: *${tv:,.0f}*   {arrow} day {dp:+,.0f} ({dpct:+.1f}%)", ""]
    movers = sorted(snap["holdings"], key=lambda h: abs(h["day_pct"]), reverse=True)[:top]
    for h in movers:
        b = "🟢" if h["day_pct"] >= 0 else "🔴"
        lines.append(f"{b} {h['symbol']:<5} {h['weight']*100:>4.1f}%  "
                     f"{h['day_pct']:+5.1f}%  ({h['day_pl']:+,.0f})")
    return "\n".join(lines)
