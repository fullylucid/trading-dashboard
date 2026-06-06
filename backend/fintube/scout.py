"""FinTube scout — the automatic searcher agent.

Pipeline (runs IN the FastAPI app process so distillation can reach the Opus worker pool,
exactly like fintube_routes._refresh_job):

    topics → discover fresh candidates → drop already-seen → rank → transcript + discovery
    distill → keep relevance ≥ threshold → persist to feed (source="scout") → push top N
    cards to the signals Telegram → footer.

Trigger: POST /api/fintube/scout (manual or via the host systemd timer twice daily).
The CLI (`python -m fintube.scout`) only previews discovery — it can't distill standalone
because the worker bus is initialized by the running app.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, Dict, List, Optional

from . import discover, distill as distill_mod, notify, store, transcripts

logger = logging.getLogger("fintube.scout")

# Tunables (sane defaults; the route can override)
LOOKBACK_DAYS = 10
PER_QUERY = 12
DISTILL_BUDGET = 14     # max videos to transcript+distill per run (worker-pool friendly)
MIN_RELEVANCE = 0.6     # 0.6–0.8 = worth a look, ≥0.8 = strong (mirrors alert tiers)
STRONG_RELEVANCE = 0.8
MAX_PUSH = 6

_running = False        # guard against overlapping scout runs


def _qualifies(doc: Dict[str, Any], min_relevance: float) -> bool:
    d = doc.get("distill")
    if not isinstance(d, dict):
        return False
    rel = d.get("relevance")
    if not isinstance(rel, (int, float)):
        # model didn't score it — fall back to its own worth_sharing verdict
        return bool(d.get("worth_sharing"))
    if rel >= STRONG_RELEVANCE:
        return True
    return rel >= min_relevance and d.get("worth_sharing", True) is not False


async def _process(cand: Dict[str, Any]) -> Dict[str, Any]:
    """Transcript + discovery-distill a single candidate; persist; return the feed doc."""
    transcript = await asyncio.to_thread(transcripts.fetch_transcript, cand["url"], 90, True)
    doc: Dict[str, Any] = {
        "video_id": cand["video_id"], "title": cand.get("title", ""),
        "channel": cand.get("channel", ""), "channel_id": cand.get("channel_id", ""),
        "published": cand.get("published", ""), "url": cand["url"],
        "category": cand.get("category", "general"),
        "source": "scout",
        "matched_queries": cand.get("matched_queries", []),
        "duration_s": cand.get("duration_s"), "view_count": cand.get("view_count"),
        "distilled_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if not transcript:
        doc["distill"] = None
        doc["error"] = "no transcript (no captions / members-only / premiere)"
    else:
        doc["distill"] = await distill_mod.distill(
            transcript, doc["title"], doc["channel"], doc["category"], mode="discovery")
        if doc["distill"] is None:
            doc["error"] = "distill failed (worker pool busy or non-JSON)"
    store.save_video(doc)   # also marks the video seen, so we never re-process it
    return doc


async def run_scout(
    *,
    send: bool = True,
    lookback_days: int = LOOKBACK_DAYS,
    per_query: int = PER_QUERY,
    distill_budget: int = DISTILL_BUDGET,
    min_relevance: float = MIN_RELEVANCE,
    max_push: int = MAX_PUSH,
) -> Dict[str, Any]:
    """Run one full discovery sweep. Returns a summary dict (also logged)."""
    global _running
    topics = store.list_topics()
    today = dt.date.today()

    candidates = await asyncio.to_thread(
        discover.discover, topics,
        lookback_days=lookback_days, per_query=per_query, today=today)

    fresh = [c for c in candidates if not store.already_seen(c["video_id"])]
    scanned = len(fresh)
    to_process = fresh[:distill_budget]
    logger.info("scout: %d candidate(s), %d fresh, distilling %d (budget %d)",
                len(candidates), scanned, len(to_process), distill_budget)

    processed: List[Dict[str, Any]] = []
    for cand in to_process:
        try:
            processed.append(await _process(cand))
        except Exception as e:  # noqa: BLE001 — one bad video shouldn't sink the run
            logger.warning("scout: failed to process %s: %s", cand.get("video_id"), e)

    qualifying = [d for d in processed if _qualifies(d, min_relevance)]
    qualifying.sort(key=lambda d: (d.get("distill") or {}).get("relevance", 0), reverse=True)
    to_push = qualifying[:max_push]

    pushed = 0
    if send:
        pushed = notify.push_videos(to_push)
        notify.push_summary(found=len(qualifying), pushed=pushed, scanned=scanned)

    summary = {
        "scanned": scanned, "distilled": len(processed),
        "qualified": len(qualifying), "pushed": pushed,
        "min_relevance": min_relevance,
        "pushed_videos": [{"video_id": d["video_id"], "title": d["title"],
                           "relevance": (d.get("distill") or {}).get("relevance")}
                          for d in to_push],
        "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    logger.info("scout done: %s", {k: summary[k] for k in
                ("scanned", "distilled", "qualified", "pushed")})
    return summary


async def run_scout_guarded(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Single-flight wrapper used by the route's background task."""
    global _running
    if _running:
        logger.info("scout already running — skipping")
        return None
    _running = True
    try:
        return await run_scout(**kwargs)
    finally:
        _running = False


def is_running() -> bool:
    return _running


# ----------------------------------------------------------------- CLI (preview only)
def _cli() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Preview FinTube discovery (no distill/push).")
    ap.add_argument("--lookback", type=int, default=LOOKBACK_DAYS)
    ap.add_argument("--per-query", type=int, default=PER_QUERY)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    topics = store.list_topics()
    cands = discover.discover(topics, lookback_days=args.lookback, per_query=args.per_query)
    fresh = [c for c in cands if not store.already_seen(c["video_id"])]
    print(json.dumps(fresh, indent=2))
    print(f"\n{len(cands)} candidate(s), {len(fresh)} fresh/unseen across "
          f"{len([t for t in topics if t.get('enabled', True)])} topic(s).")
    print("NOTE: distillation + Telegram push only run in-app via POST /api/fintube/scout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
