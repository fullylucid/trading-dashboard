"""Your real book via SnapTrade (through the dashboard API) — option positions."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

logger = logging.getLogger("options_cli.account")
BACKEND = os.getenv("CRACKDAWN_BACKEND_URL", "http://localhost:8000")


def option_positions() -> List[Dict[str, Any]]:
    """Held option contracts (filtered from the live portfolio)."""
    try:
        r = requests.get(f"{BACKEND}/api/portfolio/positions", timeout=25)
        r.raise_for_status()
        d = r.json()
        rows = d if isinstance(d, list) else d.get("positions") or d.get("holdings") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("positions fetch failed: %s", e)
        return []
    opts = []
    for p in rows:
        kind = str(p.get("type") or "").lower()
        sym = str(p.get("symbol") or "")
        # options surface either as type=option or an OCC-style symbol
        if "option" in kind or "OPT" in kind.upper() or len(sym) > 12:
            opts.append({
                "symbol": sym, "quantity": p.get("quantity"),
                "value": p.get("current_value") or p.get("market_value"),
                "unrealized_pl": p.get("unrealized_pl") or p.get("gain_loss"),
            })
    return opts
