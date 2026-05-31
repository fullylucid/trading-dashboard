"""
Crack-a-Dawn — catalyst grounding (zero-token).

We don't hand-build every catalyst fetcher. Instead we pre-fetch a little context
(recent headlines, earnings recency) to GROUND the synthesis agent, which then does
the real catalyst research itself via its own tools (WebSearch + the *-pp-cli data
CLIs). Cheap to gather, and the agent fills the gaps.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("crack_a_dawn.catalysts")
FINNHUB = "https://finnhub.io/api/v1"


def _key() -> Optional[str]:
    return os.getenv("FINNHUB_API_KEY")


def recent_headlines(ticker: str, today: Optional[_dt.date] = None,
                     days: int = 4, limit: int = 6) -> List[Dict[str, str]]:
    """Recent company headlines from Finnhub (title + source + url + ts)."""
    key = _key()
    if not key:
        return []
    today = today or _dt.date.today()
    frm = (today - _dt.timedelta(days=days)).isoformat()
    try:
        r = requests.get(
            f"{FINNHUB}/company-news",
            params={"symbol": ticker, "from": frm, "to": today.isoformat(), "token": key},
            timeout=20,
        )
        r.raise_for_status()
        items = r.json() or []
    except Exception as e:  # noqa: BLE001
        logger.warning("news fetch failed for %s: %s", ticker, e)
        return []
    out = []
    for it in items[:limit]:
        out.append({
            "headline": (it.get("headline") or "")[:200],
            "source": it.get("source") or "",
            "url": it.get("url") or "",
        })
    return out


def ground(tickers: List[str], today: Optional[_dt.date] = None) -> Dict[str, List[Dict[str, str]]]:
    """Pre-fetch headlines for the (few) flagged tickers to seed the synthesis agent."""
    out: Dict[str, List[Dict[str, str]]] = {}
    for tk in tickers:
        hl = recent_headlines(tk, today=today)
        if hl:
            out[tk] = hl
    return out
