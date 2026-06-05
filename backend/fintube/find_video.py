"""Find-this-video — resolve a YouTube video from a photo / screenshot / cam frame.

Pipeline: image -> local VLM reads the on-screen title (vision: read_title) -> clean into a
search query -> ytsearch (discover.search_titles) -> rank candidates by title similarity ->
return the top matches for the user to pick & distill. SmolVLM is the only "eyes"; there's
no Claude-vision call. Degrades clearly when the VLM isn't configured.
"""
from __future__ import annotations

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List

from . import discover, vision

logger = logging.getLogger("fintube.find_video")

_CHANNEL_SPLIT = re.compile(r"\s+[-–—]\s+")   # "Title - Channel" separators the VLM may add


def _clean_query(raw: str) -> str:
    """Normalize the VLM's title read into a search query."""
    q = (raw or "").replace("\n", " ").strip().strip('"\'')
    q = re.sub(r"\s+", " ", q)
    return q[:120].strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def rank_candidates(query: str, hits: List[Dict[str, Any]], *, limit: int = 5) -> List[Dict[str, Any]]:
    """Score each hit's title against the read query (also tries the title-only part of a
    'Title - Channel' read), best first."""
    title_only = _CHANNEL_SPLIT.split(query)[0] if query else query
    ranked = []
    for h in hits:
        t = h.get("title", "")
        score = max(_similar(query, t), _similar(title_only, t))
        ranked.append({**h, "match": round(score, 3)})
    ranked.sort(key=lambda h: h["match"], reverse=True)
    return ranked[:limit]


async def find_from_image(image_b64: str, *, mime: str = "image/jpeg",
                          max_results: int = 5) -> Dict[str, Any]:
    """Resolve candidate videos from an image. Status is one of
    'vision-unconfigured' | 'no-text-read' | 'no-matches' | 'ok'."""
    if not vision.is_configured():
        return {"status": "vision-unconfigured", "query": None, "read": None, "candidates": []}

    read = await vision.describe_image(image_b64, task="read_title", mime=mime, max_tokens=80)
    query = _clean_query(read or "")
    if not query:
        return {"status": "no-text-read", "query": None, "read": read, "candidates": []}

    hits = await asyncio.to_thread(discover.search_titles, query, n=max_results * 3)
    candidates = rank_candidates(query, hits, limit=max_results)
    return {
        "status": "ok" if candidates else "no-matches",
        "query": query, "read": read, "candidates": candidates,
    }
