"""Finance call scoring — forward return of each ticker call vs SPY over the same window,
aggregated per creator into an alpha leaderboard. Cached in Redis (1h)."""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import store

logger = logging.getLogger("fintube.scoring")
CACHE_KEY = "fintube:leaderboard"
CACHE_TTL = 3600

_DIR = {"buy": 1, "watch": 1, "hold": 0, "sell": -1}


def _hist(ticker: str, start: str):
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(start=start, auto_adjust=True)
        return df if df is not None and not df.empty else None
    except Exception as e:  # noqa: BLE001
        logger.info("yf history failed for %s: %s", ticker, e)
        return None


def _ret_from(df, start_date: str) -> Optional[float]:
    if df is None or df.empty:
        return None
    try:
        sub = df[df.index >= start_date]
        if sub.empty:
            return None
        return float(df["Close"].iloc[-1] / sub["Close"].iloc[0] - 1.0)
    except Exception:  # noqa: BLE001
        return None


def compute_leaderboard(force: bool = False) -> Dict[str, Any]:
    c = store.r()
    if c is not None and not force:
        cached = c.get(CACHE_KEY)
        if cached:
            return json.loads(cached)

    feed = store.get_feed(limit=400)
    # gather finance calls with a real ticker + a publish date
    calls = []
    earliest: Dict[str, str] = {}
    for d in feed:
        if d.get("category") != "finance":
            continue
        pub = (d.get("published") or "")[:10]
        if not pub:
            continue
        for call in (d.get("distill", {}) or {}).get("calls", []) or []:
            tk = (call.get("ticker") or "").upper().strip()
            act = (call.get("action") or "").lower()
            if not tk or not re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", tk) or act not in _DIR or _DIR[act] == 0:
                continue
            calls.append({"channel": d.get("channel", "?"), "ticker": tk, "pub": pub,
                          "dir": _DIR[act], "title": d.get("title", ""), "video_id": d.get("video_id")})
            if tk not in earliest or pub < earliest[tk]:
                earliest[tk] = pub
            earliest["SPY"] = min(earliest.get("SPY", "2999"), pub)

    hist = {tk: _hist(tk, start) for tk, start in earliest.items()}
    spy = hist.get("SPY")

    per_channel: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"calls": 0, "scored": 0, "alpha_sum": 0.0, "wins": 0, "picks": []})
    for cl in calls:
        row = per_channel[cl["channel"]]
        row["calls"] += 1
        sret = _ret_from(hist.get(cl["ticker"]), cl["pub"])
        bret = _ret_from(spy, cl["pub"])
        if sret is None or bret is None:
            continue
        signed = cl["dir"] * sret
        alpha = signed - cl["dir"] * bret
        row["scored"] += 1
        row["alpha_sum"] += alpha
        row["wins"] += 1 if signed > 0 else 0
        row["picks"].append({"ticker": cl["ticker"], "dir": cl["dir"], "ret": round(signed, 4),
                             "alpha": round(alpha, 4), "pub": cl["pub"], "title": cl["title"][:80]})

    board = []
    for ch, v in per_channel.items():
        scored = v["scored"]
        board.append({
            "channel": ch, "calls": v["calls"], "scored": scored,
            "avg_alpha": round(v["alpha_sum"] / scored, 4) if scored else None,
            "hit_rate": round(v["wins"] / scored, 3) if scored else None,
            "picks": sorted(v["picks"], key=lambda p: p["alpha"], reverse=True)[:8],
        })
    board.sort(key=lambda x: (x["avg_alpha"] is not None, x["avg_alpha"] or -9), reverse=True)
    out = {"leaderboard": board, "generated": datetime.now(timezone.utc).isoformat()}
    if c is not None:
        c.set(CACHE_KEY, json.dumps(out), ex=CACHE_TTL)
    return out
