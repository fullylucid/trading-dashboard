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

import os

from fastapi.responses import FileResponse

from fintube import (distill, find_video, ingest, scoring, scout, store, tickers,
                     transcripts, vision, visuals)

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
    transcript = await asyncio.to_thread(transcripts.fetch_transcript, meta["url"], 90, True)
    chars = len(transcript or "")
    doc: Dict[str, Any] = {
        "video_id": vid, "title": meta.get("title", ""), "channel": meta.get("channel", ""),
        "channel_id": meta.get("channel_id", ""), "published": meta.get("published", ""),
        "url": meta["url"], "category": category,
        "transcript_chars": chars,
        "transcript_quality": "none" if not chars else ("thin" if chars < 1500 else "ok"),
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


# ----------------------------------------------------------------- topics (scout briefs)
@fintube_router.get("/topics")
def topics() -> Dict[str, Any]:
    return {"topics": store.list_topics(), "categories": store.CATEGORIES}


class AddTopicReq(BaseModel):
    query: str                     # a YouTube search query
    category: str = "general"
    id: Optional[str] = None       # slug; derived from the query if omitted
    enabled: bool = True


@fintube_router.post("/topics")
def add_topic(req: AddTopicReq) -> Dict[str, Any]:
    if not req.query.strip():
        raise HTTPException(400, "query is required")
    return {"topics": store.add_topic(req.model_dump())}


@fintube_router.delete("/topics/{topic_id}")
def del_topic(topic_id: str) -> Dict[str, Any]:
    return {"topics": store.remove_topic(topic_id)}


# ----------------------------------------------------------------- scout (discovery run)
class ScoutReq(BaseModel):
    send: bool = True              # push qualifying finds to Telegram
    lookback_days: int = scout.LOOKBACK_DAYS
    min_relevance: float = scout.MIN_RELEVANCE
    max_push: int = scout.MAX_PUSH


@fintube_router.post("/scout")
async def run_scout(req: ScoutReq) -> Dict[str, Any]:
    """Kick a discovery sweep as an in-app background task (the feed/Telegram fill in as
    it finishes). The host systemd timer hits this twice daily; also callable by hand."""
    if scout.is_running():
        return {"status": "already running"}
    asyncio.create_task(scout.run_scout_guarded(
        send=req.send, lookback_days=req.lookback_days,
        min_relevance=req.min_relevance, max_push=req.max_push))
    return {"status": "started",
            "note": "discovered videos appear in the feed and Telegram as they finish"}


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


@fintube_router.delete("/video/{video_id}")
def delete_video(video_id: str) -> Dict[str, Any]:
    """Remove a video from the feed (stays suppressed from auto-discovery)."""
    removed = store.remove_video(video_id, keep_seen=True)
    return {"removed": removed, "video_id": video_id}


class RedistillReq(BaseModel):
    video_id: str


@fintube_router.post("/redistill")
async def redistill(req: RedistillReq) -> Dict[str, Any]:
    """Re-run distillation on a video already in the feed (e.g. after a prompt change),
    replacing its entry in place. Inline (~40s), like a single ingest."""
    old = store.get_video(req.video_id)
    if not old:
        raise HTTPException(404, "not in feed")
    meta = {k: old.get(k, "") for k in ("video_id", "title", "channel", "channel_id", "published")}
    meta["url"] = old.get("url") or f"https://www.youtube.com/watch?v={req.video_id}"
    cat = old.get("category", "general")
    store.remove_video(req.video_id, keep_seen=True)   # drop the stale entry; _ingest_one re-saves
    doc = await _ingest_one(meta, cat)
    return {"type": "video", "redistilled": True, "doc": doc}


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


# ----------------------------------------------------------------- find-this-video (vision)
@fintube_router.get("/vision-status")
def vision_status() -> Dict[str, Any]:
    """Lets the UI show/hide the camera 'find' tool. backend is 'pool' (Claude workers read
    the image), 'vlm' (external endpoint), or null (vision off)."""
    backend = vision.active_backend()
    return {"configured": vision.is_configured(), "backend": backend,
            "model": vision.VLM_MODEL if backend == "vlm" else "claude-pool" if backend == "pool" else None}


class FindReq(BaseModel):
    image_b64: str                 # base64 (no data: prefix needed)
    mime: str = "image/jpeg"
    max_results: int = 5


@fintube_router.post("/find")
async def find(req: FindReq) -> Dict[str, Any]:
    """Resolve a YouTube video from a photo/screenshot/cam frame via the local VLM
    (reads the on-screen title) + ytsearch. Returns ranked candidates to pick & distill."""
    if not req.image_b64:
        raise HTTPException(400, "image_b64 is required")
    return await find_video.find_from_image(
        req.image_b64, mime=req.mime, max_results=max(1, min(req.max_results, 10)))


# ----------------------------------------------------------------- visual keyframes
class VisualsReq(BaseModel):
    url: str = ""
    video_id: str = ""


@fintube_router.post("/visuals")
async def start_visuals(req: VisualsReq) -> Dict[str, Any]:
    """Kick the keyframe pipeline for a video (background). HEAVY + gated: on-demand only.
    The frames + captions fill in; poll GET /visuals/{video_id}."""
    if not vision.is_configured():
        raise HTTPException(400, "vision is not configured on this backend")
    url = req.url.strip()
    vid = req.video_id.strip()
    if not vid and url:
        kind, ident = ingest.parse_target(url)
        if kind == "video":
            vid = ident
    if vid and not url:
        url = f"https://www.youtube.com/watch?v={vid}"
    if not vid or not url:
        raise HTTPException(400, "need a video URL (or video_id)")

    existing = store.get_video(vid)
    title = (existing or {}).get("title", "")

    if visuals.is_running(vid):
        return {"status": "running", "video_id": vid}
    asyncio.create_task(visuals.run_visuals(vid, url, title))
    return {"status": "started", "video_id": vid,
            "note": "frames appear as the pipeline finishes; poll /visuals/{video_id}"}


@fintube_router.get("/visuals/{video_id}")
def get_visuals(video_id: str) -> Dict[str, Any]:
    doc = visuals.get_result(video_id)
    if not doc:
        return {"status": "none", "video_id": video_id, "frames": []}
    if visuals.is_running(video_id):
        doc["status"] = "running"
    return doc


@fintube_router.get("/visuals/{video_id}/frame/{idx}")
def get_visual_frame(video_id: str, idx: int):
    path = visuals.frame_path(video_id, idx)
    if not os.path.isfile(path):
        raise HTTPException(404, "frame not found")
    return FileResponse(path, media_type="image/jpeg")


# ----------------------------------------------------------------- ticker intelligence
@fintube_router.get("/tickers")
async def ticker_intel(force: bool = False) -> Dict[str, Any]:
    """Per-ticker rollup across the finance feed: crowd stance, who-called-it + their
    track record, live price/return, avg target, and a consensus/contrarian read."""
    return await asyncio.to_thread(tickers.compute_ticker_intel, force)
