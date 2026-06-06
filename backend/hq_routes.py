"""Hydra HQ API — fleet command center (DESIGN.md §7).

Thin, read-only passthrough of the ``hq:fleet`` snapshot that the host-side collector
(scripts/hq_collector.py) pushes to Redis every ~10s. The backend runs in Docker and can't
see host paths/tmux/git/gh, so ALL aggregation happens on the host; this router just serves
the pre-built, already-redacted snapshot to the /hq route.

Same ``_r()``/APIRouter pattern as system_routes.py. Everything here is sync, cheap, and
~0 tokens. Lives behind the existing Cloudflare Access SSO with the rest of the dashboard.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

hq_router = APIRouter(prefix="/api/hq", tags=["hq"])
logger = logging.getLogger("hq_routes")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FLEET_KEY = "hq:fleet"
ROOMS_KEY = "hq:rooms"
MEMORY_KEY = "hq:memory"

_redis_client: Optional["redis.Redis"] = None


def _r() -> Optional["redis.Redis"]:
    global _redis_client
    if redis is None:
        return None
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            _redis_client.ping()
        except Exception as e:  # noqa: BLE001
            logger.warning("hq_routes redis unavailable: %s", e)
            _redis_client = None
    return _redis_client


def _get_json(r, key: str) -> Optional[Any]:
    raw = r.get(key) if r is not None else None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


@hq_router.get("/fleet")
def fleet() -> Dict[str, Any]:
    """The whole-fleet snapshot: rooms, heads (status/current/branch/git), activity, memory.

    Read-only passthrough of Redis ``hq:fleet`` (built host-side by hq_collector.py). Returns
    ``{"available": false}`` if the collector hasn't run yet / the key expired, so the UI can
    show a clean "collector offline" state instead of erroring.
    """
    data = _get_json(_r(), FLEET_KEY)
    if data is None:
        return {"available": False}
    data["available"] = True
    return data


@hq_router.get("/room/{room_id}")
def room(room_id: str) -> Dict[str, Any]:
    """One project room: its heads + open PRs (from the fleet snapshot) merged with its
    rendered key docs (README/blueprint/roadmap/architecture, from ``hq:rooms``).

    404 if the room isn't in the current snapshot; ``{"available": false}`` if the collector
    hasn't run at all. Docs are already secret-scrubbed + size-capped host-side.
    """
    r = _r()
    fleet_data = _get_json(r, FLEET_KEY)
    if fleet_data is None:
        return {"available": False}

    match = next((rm for rm in fleet_data.get("rooms", []) if rm.get("id") == room_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"unknown room: {room_id}")

    rooms_detail = _get_json(r, ROOMS_KEY) or {}
    docs = (rooms_detail.get("rooms", {}).get(room_id, {}) or {}).get("docs", [])

    heads = [h for h in fleet_data.get("heads", []) if h.get("room") == room_id]
    return {
        "available": True,
        "generated_at": fleet_data.get("generated_at"),
        "room": {**match, "docs": docs},
        "heads": heads,
    }


@hq_router.get("/memory")
def memory_index() -> Dict[str, Any]:
    """The memory knowledge-base index: one lightweight entry per ``memory/*.md`` (name, title,
    description, type, scope, link count). Bodies are fetched per-doc via /memory/{name}.

    Read-only passthrough of ``hq:memory`` (built + secret-scrubbed host-side from the
    git-tracked memory dir). ``{"available": false}`` if the collector hasn't run.
    """
    data = _get_json(_r(), MEMORY_KEY)
    if data is None:
        return {"available": False}
    return {
        "available": True,
        "generated_at": data.get("generated_at"),
        "index": data.get("index", []),
    }


@hq_router.get("/memory/{name}")
def memory_doc(name: str) -> Dict[str, Any]:
    """One memory doc: its frontmatter + scrubbed body + outbound/inbound ``[[wikilinks]]``.

    ``links_out`` is annotated with whether each target exists (so the UI can style broken
    links). 404 if the name isn't in the knowledge base.
    """
    data = _get_json(_r(), MEMORY_KEY)
    if data is None:
        return {"available": False}
    docs = data.get("docs", {})
    doc = docs.get(name)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"unknown memory: {name}")
    links_out = [{"name": l, "exists": l in docs} for l in doc.get("links_out", [])]
    return {"available": True, "generated_at": data.get("generated_at"), "doc": {**doc, "links_out": links_out}}
