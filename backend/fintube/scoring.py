"""Finance call scoring — forward return of each ticker call vs SPY over the call's own
stated HORIZON (not blindly to today), aggregated per creator into an alpha leaderboard.

Each directional call (buy/sell) is scored over ``[publish_date, publish_date + horizon]``.
If that window hasn't closed yet the call is scored to-date and flagged ``in_flight`` so a
3-day call from last week isn't judged on a 5-month drift. ``watch`` calls are tracked
(``watch_calls``) but NOT scored — they aren't directional bets; ``hold`` is ignored. A
"hit" is positive ALPHA (beat SPY over the window), consistent with the alpha framing.

Price history is cached per-ticker for the current day (``_PRICE_CACHE``) so repeated
recomputes don't re-download, and the whole board is cached in Redis (1h). Date masks are
tz-normalized so tz-aware yfinance indices compare cleanly against ISO date strings.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from . import store

logger = logging.getLogger("fintube.scoring")
CACHE_KEY = "fintube:leaderboard"
CACHE_TTL = 3600

# Only directional calls are scored for alpha. `watch` is tracked separately; `hold` ignored.
_DIR = {"buy": 1, "sell": -1}

_HORIZON_DEFAULT_DAYS = 90
_HORIZON_CAP_DAYS = 3 * 365
_TICKER_RE = re.compile(r"[A-Z][A-Z.\-]{0,6}")

# in-process price cache: ticker -> {"day": iso, "start": iso, "df": DataFrame|None}
_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}


def horizon_to_days(horizon: Optional[str]) -> int:
    """Map a fuzzy horizon phrase ('days', '2 weeks', '1-3yr') to a window in days.

    Range phrases take the LARGER bound (give the call its full stated runway). A unit with
    no number uses a sensible default (days→7, weeks→14, months→90). Unknown/empty →
    ``_HORIZON_DEFAULT_DAYS``. Capped at 3 years.
    """
    if not horizon:
        return _HORIZON_DEFAULT_DAYS
    h = horizon.lower()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", h)]
    if "year" in h or "yr" in h:
        unit, default_n = 365, 1.5
    elif "quarter" in h:
        unit, default_n = 90, 1.0
    elif "month" in h or "mo" in h:
        unit, default_n = 30, 3.0
    elif "week" in h or "wk" in h:
        unit, default_n = 7, 2.0
    elif "day" in h:
        unit, default_n = 1, 7.0
    else:
        return _HORIZON_DEFAULT_DAYS
    n = max(nums) if nums else default_n
    return int(max(1, min(unit * n, _HORIZON_CAP_DAYS)))


def _fetch_hist(ticker: str, start: str):
    """Raw yfinance pull (the cache wraps this)."""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).history(start=start, auto_adjust=True)
        return df if df is not None and not df.empty else None
    except Exception as e:  # noqa: BLE001
        logger.info("yf history failed for %s: %s", ticker, e)
        return None


def _hist(ticker: str, start: str, today: Optional[dt.date] = None):
    """Day-cached price history. Reuses today's cached frame when it already covers `start`,
    otherwise (re)fetches from the earlier of the requested and previously-cached start."""
    today_iso = (today or dt.date.today()).isoformat()
    cached = _PRICE_CACHE.get(ticker)
    if cached and cached["day"] == today_iso and cached["start"] <= start:
        return cached["df"]
    fetch_start = min(start, cached["start"]) if cached else start
    df = _fetch_hist(ticker, fetch_start)
    _PRICE_CACHE[ticker] = {"day": today_iso, "start": fetch_start, "df": df}
    return df


def clear_price_cache() -> None:
    """Drop the in-process price cache (used by tests / a hard recompute)."""
    _PRICE_CACHE.clear()


def _ret_over(df, start_date: str, end_date: str) -> Optional[float]:
    """Return over ``[start_date, end_date]``: first close on/after start to last close
    on/before end. tz-normalizes the index so tz-aware yfinance frames don't raise."""
    if df is None or getattr(df, "empty", True):
        return None
    try:
        import pandas as pd
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        mask = (idx >= pd.Timestamp(start_date)) & (idx <= pd.Timestamp(end_date))
        win = df[mask]
        if win.empty:
            return None
        return float(win["Close"].iloc[-1] / win["Close"].iloc[0] - 1.0)
    except Exception:  # noqa: BLE001
        return None


def compute_leaderboard(force: bool = False, today: Optional[dt.date] = None) -> Dict[str, Any]:
    c = store.r()
    if c is not None and not force:
        cached = c.get(CACHE_KEY)
        if cached:
            return json.loads(cached)

    today = today or dt.date.today()
    feed = store.get_feed(limit=400)

    per_channel: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "scored": 0, "settled": 0, "in_flight": 0,
                 "watch_calls": 0, "alpha_sum": 0.0, "wins": 0, "picks": []})

    # collect directional calls; track earliest pub per ticker for one history fetch
    calls: List[Dict[str, Any]] = []
    earliest: Dict[str, str] = {}
    for d in feed:
        if d.get("category") != "finance":
            continue
        pub = (d.get("published") or "")[:10]
        if not pub:
            continue
        ch = d.get("channel", "?")
        for call in (d.get("distill") or {}).get("calls", []) or []:
            act = (call.get("action") or "").lower()
            if act == "watch":
                per_channel[ch]["watch_calls"] += 1
                continue
            if act not in _DIR:
                continue
            tk = (call.get("ticker") or "").upper().strip()
            if not tk or not _TICKER_RE.fullmatch(tk):
                continue
            calls.append({"channel": ch, "ticker": tk, "pub": pub, "dir": _DIR[act],
                          "horizon_days": horizon_to_days(call.get("horizon")),
                          "title": d.get("title", ""), "video_id": d.get("video_id")})
            if tk not in earliest or pub < earliest[tk]:
                earliest[tk] = pub
            earliest["SPY"] = min(earliest.get("SPY", "9999"), pub)

    hist = {tk: _hist(tk, start, today=today) for tk, start in earliest.items()}
    spy = hist.get("SPY")

    for cl in calls:
        row = per_channel[cl["channel"]]
        row["calls"] += 1
        window_end = dt.date.fromisoformat(cl["pub"]) + dt.timedelta(days=cl["horizon_days"])
        in_flight = window_end > today
        eval_end = min(window_end, today).isoformat()
        sret = _ret_over(hist.get(cl["ticker"]), cl["pub"], eval_end)
        bret = _ret_over(spy, cl["pub"], eval_end)
        if sret is None or bret is None:
            continue
        signed = cl["dir"] * sret
        alpha = signed - cl["dir"] * bret
        row["scored"] += 1
        row["in_flight" if in_flight else "settled"] += 1
        row["alpha_sum"] += alpha
        row["wins"] += 1 if alpha > 0 else 0
        row["picks"].append({"ticker": cl["ticker"], "dir": cl["dir"],
                             "ret": round(signed, 4), "alpha": round(alpha, 4),
                             "pub": cl["pub"], "horizon_days": cl["horizon_days"],
                             "window_end": window_end.isoformat(), "in_flight": in_flight,
                             "title": cl["title"][:80]})

    board = []
    for ch, v in per_channel.items():
        scored = v["scored"]
        board.append({
            "channel": ch, "calls": v["calls"], "scored": scored,
            "settled": v["settled"], "in_flight": v["in_flight"],
            "watch_calls": v["watch_calls"],
            "avg_alpha": round(v["alpha_sum"] / scored, 4) if scored else None,
            "hit_rate": round(v["wins"] / scored, 3) if scored else None,
            "picks": sorted(v["picks"], key=lambda p: p["alpha"], reverse=True)[:8],
        })
    board.sort(key=lambda x: (x["avg_alpha"] is not None, x["avg_alpha"] or -9), reverse=True)
    out = {"leaderboard": board, "generated": dt.datetime.now(dt.timezone.utc).isoformat()}
    if c is not None:
        c.set(CACHE_KEY, json.dumps(out), ex=CACHE_TTL)
    return out
