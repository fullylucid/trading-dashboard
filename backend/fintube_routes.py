"""FinTube API — tracked-channel registry, ad-hoc ingest of any channel/video,
category-aware distillation (Opus pool), and the finance alpha leaderboard.

Single-video ingest runs inline (one ~40s request). Refreshing all tracked channels
runs in a background task (the feed fills in as videos finish); the browser polls the feed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fintube import distill, ingest, scoring, store, transcripts

fintube_router = APIRouter(prefix="/api/fintube", tags=["fintube"])
logger = logging.getLogger("fintube_routes")

_refreshing = False  # guard against overlapping background refreshes


def _channel_category(channel_id: str) -> str:
    for ch in store.list_channels():
        if ch["id"] == channel_id:
            return ch.get("category", "general")
    return "general"


async def _ingest_one(meta: Dict[str, Any], category: str) -> Dict[str, Any]:
    """Fetch transcript + distill a single video, persist, return the doc."""
    vid = meta["video_id"]
    transcript = await asyncio.to_thread(transcripts.fetch_transcript, meta["url"])
    doc: Dict[str, Any] = {
        "video_id": vid, "title": meta.get("title", ""), "channel": meta.get("channel", ""),
        "channel_id": meta.get("channel_id", ""), "published": meta.get("published", ""),
        "url": meta["url"], "category": category,
        "distilled_at": datetime.now(timezone.utc).isoformat(),
    }
    if not transcript:
        doc["distill"] = None
        doc["error"] = "no transcript available (no captions / members-only / premiere)"
    else:
        doc["distill"] = await distill.distill(transcript, doc["title"], doc["channel"], category)
        if doc["distill"] is None:
            doc["error"] = "distill failed (worker pool busy or non-JSON)"
    store.save_video(doc)
    return doc


# ----------------------------------------------------------------- channels
@fintube_router.get("/channels")
def channels() -> Dict[str, Any]:
    return {"channels": store.list_channels(), "categories": store.CATEGORIES}


class AddChannelReq(BaseModel):
    url: str                       # @handle, /channel/UC..., or channel URL
    category: str = "general"


@fintube_router.post("/channels")
def add_channel(req: AddChannelReq) -> Dict[str, Any]:
    ch = ingest.resolve_channel(req.url)
    if not ch:
        raise HTTPException(404, "could not resolve that channel")
    cat = req.category if req.category in store.CATEGORIES else "general"
    chans = store.add_channel({"id": ch["id"], "handle": ch.get("handle", ""),
                               "name": ch.get("name", ch["id"]), "category": cat})
    return {"added": ch, "channels": chans}


@fintube_router.delete("/channels/{channel_id}")
def del_channel(channel_id: str) -> Dict[str, Any]:
    return {"channels": store.remove_channel(channel_id)}


# ----------------------------------------------------------------- feed
@fintube_router.get("/feed")
def feed(category: Optional[str] = None, limit: int = 60) -> Dict[str, Any]:
    return {"videos": store.get_feed(limit=limit, category=category)}


@fintube_router.get("/video/{video_id}")
def video(video_id: str) -> Dict[str, Any]:
    d = store.get_video(video_id)
    if not d:
        raise HTTPException(404, "not in feed")
    return d


# ----------------------------------------------------------------- ad-hoc ingest
class IngestReq(BaseModel):
    url: str
    category: str = "general"
    track: bool = False            # if a channel, also add it to the tracked list


@fintube_router.post("/ingest")
async def ingest_url(req: IngestReq) -> Dict[str, Any]:
    kind, ident = ingest.parse_target(req.url)
    cat = req.category if req.category in store.CATEGORIES else "general"

    if kind == "video":
        meta = await asyncio.to_thread(ingest.video_meta, ident)
        if not meta:
            raise HTTPException(404, "could not read that video (private/members/removed?)")
        # if we already distilled it, return cached
        existing = store.get_video(meta["video_id"])
        if existing and existing.get("distill"):
            return {"type": "video", "cached": True, "doc": existing}
        # inherit category from a tracked channel if we know it
        if cat == "general":
            cat = _channel_category(meta.get("channel_id", "")) or "general"
        doc = await _ingest_one(meta, cat)
        return {"type": "video", "doc": doc}

    if kind == "channel":
        ch = await asyncio.to_thread(ingest.resolve_channel, ident)
        if not ch:
            raise HTTPException(404, "could not resolve that channel")
        if req.track:
            store.add_channel({"id": ch["id"], "handle": ch.get("handle", ""),
                               "name": ch.get("name", ch["id"]), "category": cat})
        recents = await asyncio.to_thread(ingest.channel_recent_public, ch["id"], 1)
        doc = None
        if recents:
            doc = await _ingest_one(recents[0], cat)
        return {"type": "channel", "channel": ch, "tracked": req.track, "doc": doc}

    raise HTTPException(400, "could not parse that as a video or channel URL")


# ----------------------------------------------------------------- refresh tracked
async def _refresh_job(max_new: int = 8) -> None:
    global _refreshing
    try:
        done = 0
        for ch in store.list_channels():
            recents = await asyncio.to_thread(ingest.channel_recent_public, ch["id"], 5)
            for v in recents:
                if done >= max_new:
                    return
                if store.already_seen(v["video_id"]):
                    continue
                await _ingest_one(v, ch.get("category", "general"))
                done += 1
    finally:
        _refreshing = False


@fintube_router.post("/refresh")
async def refresh() -> Dict[str, Any]:
    global _refreshing
    if _refreshing:
        return {"status": "already running"}
    _refreshing = True
    asyncio.create_task(_refresh_job())
    return {"status": "started", "note": "new videos appear in the feed as they finish"}


# ----------------------------------------------------------------- leaderboard
@fintube_router.get("/leaderboard")
async def leaderboard(force: bool = False) -> Dict[str, Any]:
    return await asyncio.to_thread(scoring.compute_leaderboard, force)
