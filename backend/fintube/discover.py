"""Discovery — search YouTube by topic for *new* videos, not just tracked channels.

This is what turns FinTube from a channel-poller into a scout: given a query, run
yt-dlp's `ytsearch` (no API key, no quota — same approach as ingest.py), pull recent
results with full metadata, then keep only videos that are (a) fresh, (b) long enough
to be substantive (skips Shorts / teasers), and (c) not already in the feed.

yt-dlp returns search hits by relevance, so we over-fetch and date-filter ourselves
rather than trusting the order.
"""
from __future__ import annotations

import datetime as dt
import logging
import subprocess
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fintube.discover")

# id|upload_date(YYYYMMDD)|duration(sec)|view_count|channel_id|channel|title
_FMT = "%(id)s\t%(upload_date)s\t%(duration)s\t%(view_count)s\t%(channel_id)s\t%(channel)s\t%(title)s"

MIN_DURATION_S = 180      # < 3 min ⇒ Short/teaser, rarely worth distilling
MAX_DURATION_S = 4 * 3600  # > 4h ⇒ stream/VOD, transcript too long to be useful


def _search_raw(query: str, n: int, timeout: int) -> List[str]:
    """Run a single ytsearch query, return raw tab-rows (full extraction, not flat —
    flat-playlist omits upload_date/duration which we need to filter on)."""
    target = f"ytsearch{n}:{query}"
    cmd = [
        sys.executable, "-m", "yt_dlp", "--no-warnings", "--quiet",
        "--ignore-errors",          # one unplayable hit shouldn't kill the batch
        "--no-playlist",
        "--print", _FMT,
        target,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    except subprocess.TimeoutExpired:
        logger.warning("ytsearch timeout for %r", query)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("ytsearch failed for %r: %s", query, e)
        return []


def _parse_row(row: str) -> Optional[Dict[str, Any]]:
    parts = row.split("\t")
    if len(parts) < 7:
        return None
    vid, ud, dur, views, cid, channel, title = parts[:7]
    if not vid or len(vid) != 11:
        return None
    iso = f"{ud[:4]}-{ud[4:6]}-{ud[6:8]}" if len(ud) == 8 and ud.isdigit() else ""

    def _int(x: str) -> Optional[int]:
        try:
            return int(float(x))
        except (TypeError, ValueError):
            return None

    return {
        "video_id": vid,
        "title": title,
        "channel": channel,
        "channel_id": cid,
        "published": iso,
        "duration_s": _int(dur),
        "view_count": _int(views),
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def search_recent(
    query: str,
    *,
    lookback_days: int = 10,
    per_query: int = 12,
    timeout: int = 150,
    today: Optional[dt.date] = None,
) -> List[Dict[str, Any]]:
    """Search a single topic query and return fresh, substantive candidates.

    Filters: published within `lookback_days`, duration in [MIN, MAX]. Videos with an
    unknown upload_date are dropped (we can't confirm freshness, and discovery is about
    *new* material). Returns newest-first.
    """
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=lookback_days)
    out: List[Dict[str, Any]] = []
    for row in _search_raw(query, per_query, timeout):
        c = _parse_row(row)
        if not c or not c["published"]:
            continue
        try:
            pub = dt.date.fromisoformat(c["published"])
        except ValueError:
            continue
        if pub < cutoff:
            continue
        dur = c["duration_s"]
        if dur is not None and (dur < MIN_DURATION_S or dur > MAX_DURATION_S):
            continue
        c["query"] = query
        out.append(c)
    out.sort(key=lambda c: c["published"], reverse=True)
    return out


def discover(
    topics: List[Dict[str, Any]],
    *,
    lookback_days: int = 10,
    per_query: int = 12,
    timeout: int = 150,
    today: Optional[dt.date] = None,
) -> List[Dict[str, Any]]:
    """Run every enabled topic query and merge results, de-duplicating by video_id.

    Each topic is a dict {query, category, ...}. A video found by multiple queries keeps
    its first hit but accumulates the matching queries in `matched_queries` (a small
    relevance signal — broad interest across topics).
    """
    by_id: Dict[str, Dict[str, Any]] = {}
    for t in topics:
        if not t.get("enabled", True):
            continue
        query = t.get("query", "").strip()
        if not query:
            continue
        cat = t.get("category", "general")
        hits = search_recent(query, lookback_days=lookback_days, per_query=per_query,
                              timeout=timeout, today=today)
        logger.info("discover %r (%s) -> %d fresh candidate(s)", query, cat, len(hits))
        for h in hits:
            existing = by_id.get(h["video_id"])
            if existing:
                existing["matched_queries"].append(query)
                continue
            h["category"] = cat
            h["matched_queries"] = [query]
            by_id[h["video_id"]] = h
    merged = list(by_id.values())
    merged.sort(key=lambda c: (len(c["matched_queries"]), c["published"]), reverse=True)
    return merged


if __name__ == "__main__":  # quick manual smoke test (no Redis / no worker needed)
    import json
    q = " ".join(sys.argv[1:]) or "algorithmic trading strategy python backtest"
    res = search_recent(q, lookback_days=30, per_query=8)
    print(json.dumps(res, indent=2))
    print(f"\n{len(res)} candidate(s) for {q!r}")
