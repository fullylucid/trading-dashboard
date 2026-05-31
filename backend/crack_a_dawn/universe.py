"""
Crack-a-Dawn — universe assembly (zero-token).

Holdings come from the backend portfolio API (deduped + weight-aggregated across
accounts). Watchlist comes from a simple curatable file (SnapTrade's watchlist is
empty), so Schyler can add names to watch without touching the brokerage.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Set, Tuple

import requests

logger = logging.getLogger("crack_a_dawn.universe")

BACKEND = os.getenv("CRACKDAWN_BACKEND_URL", "http://localhost:8000")
WATCHLIST_FILE = os.getenv(
    "CRACKDAWN_WATCHLIST_FILE", os.path.expanduser("~/.config/trading-dashboard/watchlist.txt")
)


def _holdings() -> Dict[str, float]:
    """ticker -> aggregated book weight (0..1), deduped across accounts."""
    try:
        r = requests.get(f"{BACKEND}/api/portfolio/positions", timeout=30)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("positions") or data.get("holdings") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("holdings fetch failed: %s", e)
        return {}
    agg: Dict[str, float] = {}
    for p in rows:
        sym = (p.get("symbol") or p.get("ticker") or "").upper().strip()
        if not sym:
            continue
        w = p.get("weight") or p.get("allocation") or 0.0
        agg[sym] = agg.get(sym, 0.0) + float(w or 0.0)
    return agg


def _watchlist() -> Set[str]:
    """Tickers from the curatable file (one per line, '#' comments)."""
    try:
        with open(WATCHLIST_FILE) as f:
            return {
                ln.strip().upper() for ln in f
                if ln.strip() and not ln.lstrip().startswith("#")
            }
    except FileNotFoundError:
        return set()
    except Exception as e:  # noqa: BLE001
        logger.warning("watchlist read failed: %s", e)
        return set()


def get_universe() -> Tuple[Dict[str, float], List[str]]:
    """Returns (held_weights, all_tickers). all_tickers = holdings ∪ watchlist, deduped."""
    held = _holdings()
    watch = _watchlist()
    tickers = sorted(set(held) | watch)
    logger.info("universe: %d held, %d watch, %d total", len(held), len(watch), len(tickers))
    return held, tickers
