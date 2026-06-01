"""
2Chainz — context gather (zero-token). What makes it a portfolio STRATEGIST
and not a generic chatbot: it always knows the live book + this morning's brief.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import requests

logger = logging.getLogger("twochainz.context")
BACKEND = os.getenv("CRACKDAWN_BACKEND_URL", "http://localhost:8000")


def _book() -> str:
    try:
        r = requests.get(f"{BACKEND}/api/portfolio/positions", timeout=20)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("positions") or data.get("holdings") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("book fetch failed: %s", e)
        return "(book unavailable)"
    agg: Dict[str, Dict[str, float]] = {}
    for p in rows:
        sym = (p.get("symbol") or p.get("ticker") or "").upper().strip()
        if not sym:
            continue
        a = agg.setdefault(sym, {"w": 0.0, "v": 0.0, "upl": 0.0, "cost": 0.0})
        a["w"] += float(p.get("weight") or p.get("allocation") or 0.0)
        a["v"] += float(p.get("current_value") or p.get("market_value") or p.get("value") or 0.0)
        a["upl"] += float(p.get("unrealized_pl") or p.get("gain_loss") or 0.0)
        a["cost"] += float(p.get("cost_basis") or 0.0)
    ranked = sorted(agg.items(), key=lambda kv: kv[1]["w"], reverse=True)
    total = sum(d["v"] for d in agg.values())
    lines = []
    for s, d in ranked:
        pct = (d["upl"] / d["cost"] * 100.0) if d["cost"] else 0.0
        lines.append(f"  {s}: {d['w']*100:.1f}% (${d['v']:,.0f}, unrealized {d['upl']:+,.0f} / {pct:+.1f}%)")
    head = f"HOLDINGS — total ${total:,.0f} (weight, value, unrealized P&L vs cost):"
    return head + "\n" + "\n".join(lines) if lines else "(empty book)"


def _latest_brief() -> Optional[str]:
    try:
        r = requests.get(f"{BACKEND}/api/brief/latest", timeout=15)
        if r.status_code == 200:
            return r.json().get("brief_markdown")
    except Exception as e:  # noqa: BLE001
        logger.warning("brief fetch failed: %s", e)
    return None


def gather() -> str:
    """A compact context block injected into every strategist turn."""
    parts = [_book()]
    brief = _latest_brief()
    if brief:
        parts.append("TODAY'S CRACK-A-DAWN BRIEF (your shared morning context):\n" + brief)
    return "\n\n".join(parts)
