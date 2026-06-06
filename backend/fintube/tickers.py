"""Ticker Intelligence — pivots the distilled finance feed from per-video to per-ticker.

For every ticker called across the feed it aggregates: the crowd's stance (buy/sell/watch
counts + a lean), who said what, each creator's track record (avg α / hit rate from the
alpha leaderboard), the live price + return since the first call, an average price target
(+ implied upside), and a consensus / contrarian read — does the best-track-record creator
on this name agree with the crowd, or fade it? Cached in Redis (1h).

This is the trader-facing rollup: "what's the YouTube consensus on NVDA, who called it,
and have they been right?" — a question the per-video feed can't answer.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from . import scoring, store

logger = logging.getLogger("fintube.tickers")
CACHE_KEY = "fintube:tickers"
CACHE_TTL = 3600

_TICKER_RE = re.compile(r"[A-Z][A-Z.\-]{0,6}")
_STRONG_LEAN = 0.6   # |crowd_lean| at/above this == one-sided crowd
_DIR = {"buy": 1, "sell": -1}


def _median(xs: List[float]) -> Optional[float]:
    """Median — robust to one creator's moonshot target skewing a mean."""
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def _signal(mentions: int, crowd_lean: float, smart_agrees: Optional[bool],
            directional: int) -> str:
    """Human-readable read combining crowd one-sidedness with the smart-money tilt."""
    if not directional:
        return "watchlist"                      # only watch/hold calls
    side = "long" if crowd_lean > 0 else "short" if crowd_lean < 0 else "split"
    if smart_agrees is False:
        return f"contrarian — top creator fades the {side} crowd"
    if mentions == 1:
        return f"single {side} call"
    if abs(crowd_lean) >= _STRONG_LEAN:
        return f"consensus {side}"
    return f"leaning {side}" if side != "split" else "split"


def _current_and_first(df, first_pub: str):
    """(latest close, first close on/after first_pub) or (None, None) — tz-safe."""
    if df is None or getattr(df, "empty", True):
        return None, None
    try:
        import pandas as pd
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        latest = float(df["Close"].iloc[-1])
        after = df[idx >= pd.Timestamp(first_pub)]
        first = float(after["Close"].iloc[0]) if not after.empty else None
        return latest, first
    except Exception:  # noqa: BLE001
        return None, None


def compute_ticker_intel(force: bool = False, today: Optional[dt.date] = None) -> Dict[str, Any]:
    c = store.r()
    if c is not None and not force:
        cached = c.get(CACHE_KEY)
        if cached:
            return json.loads(cached)

    today = today or dt.date.today()
    feed = store.get_feed(limit=400)

    # per-creator track record from the alpha leaderboard (shares its Redis cache)
    board = scoring.compute_leaderboard(force=force, today=today).get("leaderboard", [])
    track = {row["channel"]: {"avg_alpha": row.get("avg_alpha"),
                              "hit_rate": row.get("hit_rate"),
                              "scored": row.get("scored", 0)} for row in board}

    by_ticker: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"calls": [], "buy": 0, "sell": 0, "watch": 0, "hold": 0,
                 "first_pub": None, "last_pub": None, "targets": []})

    for d in feed:
        if d.get("category") != "finance":
            continue
        pub = (d.get("published") or "")[:10]
        ch = d.get("channel", "?")
        for call in (d.get("distill") or {}).get("calls", []) or []:
            tk = (call.get("ticker") or "").upper().strip()
            if not tk or not _TICKER_RE.fullmatch(tk):
                continue
            act = (call.get("action") or "").lower()
            rec = by_ticker[tk]
            if act in ("buy", "sell", "watch", "hold"):
                rec[act] += 1
            tr = track.get(ch, {})
            rec["calls"].append({
                "channel": ch, "action": act, "conviction": call.get("conviction"),
                "horizon": call.get("horizon"), "price_target": call.get("price_target"),
                "thesis": call.get("thesis"), "pub": pub, "title": d.get("title", ""),
                "video_id": d.get("video_id"), "url": d.get("url", ""),
                "creator_alpha": tr.get("avg_alpha"), "creator_scored": tr.get("scored", 0),
            })
            if pub:
                rec["first_pub"] = pub if rec["first_pub"] is None else min(rec["first_pub"], pub)
                rec["last_pub"] = pub if rec["last_pub"] is None else max(rec["last_pub"], pub)
            pt = call.get("price_target")
            if isinstance(pt, (int, float)) and not isinstance(pt, bool) and pt > 0:
                rec["targets"].append(float(pt))

    out_tickers: List[Dict[str, Any]] = []
    for tk, rec in by_ticker.items():
        buy, sell, watch = rec["buy"], rec["sell"], rec["watch"]
        directional = buy + sell
        crowd_lean = (buy - sell) / directional if directional else 0.0
        mentions = len(rec["calls"])

        price = first_price = ret_since = None
        if rec["first_pub"]:
            df = scoring._hist(tk, rec["first_pub"], today=today)
            price, first_price = _current_and_first(df, rec["first_pub"])
            if price is not None and first_price:
                ret_since = round(price / first_price - 1.0, 4)

        # distinct creators — keep each creator's most recent stance, ranked by track record
        creators: Dict[str, Dict[str, Any]] = {}
        for cl in rec["calls"]:
            ch = cl["channel"]
            cur = creators.get(ch)
            if cur is None or (cl["pub"] or "") >= (cur["pub"] or ""):
                creators[ch] = {"channel": ch, "action": cl["action"],
                                "conviction": cl["conviction"], "pub": cl["pub"],
                                "avg_alpha": cl["creator_alpha"], "scored": cl["creator_scored"]}
        creator_list = sorted(creators.values(),
                              key=lambda x: (x["avg_alpha"] is not None, x["avg_alpha"] or -9),
                              reverse=True)

        # smart-money read: best-track-record creator (scored>0) with a directional stance
        top = next((cr for cr in creator_list
                    if (cr["scored"] or 0) > 0 and cr["action"] in _DIR), None)
        smart_agrees: Optional[bool] = None
        if top and directional:
            crowd_dir = 1 if crowd_lean > 0 else -1 if crowd_lean < 0 else 0
            if crowd_dir:
                smart_agrees = (_DIR[top["action"]] == crowd_dir)

        targets = rec["targets"]
        med = _median(targets)
        med_target = round(med, 2) if med is not None else None
        upside = round(med_target / price - 1.0, 4) if (med_target and price) else None

        out_tickers.append({
            "ticker": tk, "mentions": mentions, "buy": buy, "sell": sell,
            "watch": watch, "hold": rec["hold"],
            "crowd_lean": round(crowd_lean, 3),
            "net": "bullish" if crowd_lean > 0.1 else "bearish" if crowd_lean < -0.1 else "mixed",
            "first_pub": rec["first_pub"], "last_pub": rec["last_pub"],
            "price": round(price, 2) if price is not None else None,
            "ret_since_first": ret_since,
            "price_target": med_target, "target_n": len(targets), "upside": upside,
            "smart_agrees": smart_agrees,
            "top_creator": top["channel"] if top else None,
            "signal": _signal(mentions, crowd_lean, smart_agrees, directional),
            "creators": creator_list,
            "calls": sorted(rec["calls"], key=lambda c: c["pub"] or "", reverse=True),
        })

    # rank: most-mentioned first, then most recent activity
    out_tickers.sort(key=lambda t: (t["mentions"], t["last_pub"] or ""), reverse=True)
    out = {"tickers": out_tickers, "generated": dt.datetime.now(dt.timezone.utc).isoformat()}
    if c is not None:
        c.set(CACHE_KEY, json.dumps(out), ex=CACHE_TTL)
    return out
