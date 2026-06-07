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

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

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
HEADS_KEY = "hq:heads"

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


@hq_router.get("/head/{name}")
def head(name: str) -> Dict[str, Any]:
    """One head's detail: its fleet card (status/current/git/branch/rc) merged with its recent
    commits, fossil-archive index, and memory scope (from ``hq:heads``), plus the open PRs it
    owns. 404 if the head isn't in the current snapshot.

    Fossils ship as a metadata index only (names/sizes/mtimes) — never bodies (DESIGN §8).
    """
    r = _r()
    fleet_data = _get_json(r, FLEET_KEY)
    if fleet_data is None:
        return {"available": False}

    card = next((h for h in fleet_data.get("heads", []) if h.get("name") == name), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"unknown head: {name}")

    detail = (_get_json(r, HEADS_KEY) or {}).get("heads", {}).get(name, {})
    open_prs = [
        pr for rm in fleet_data.get("rooms", []) for pr in rm.get("open_prs", [])
        if pr.get("head") == name
    ]
    return {
        "available": True,
        "generated_at": fleet_data.get("generated_at"),
        "head": {
            **card,
            "recent_commits": detail.get("recent_commits", []),
            "fossils": detail.get("fossils", {"count": 0, "files": []}),
            "memory_scope": detail.get("memory_scope", []),
            "open_prs": open_prs,
        },
    }


@hq_router.post("/room/{room_id}/app")
async def room_app_control(room_id: str, request: Request) -> Dict[str, Any]:
    """Run/stop the room's app from HQ (B3, per CONTROL.md). Body: ``{"action": "run"|"stop"}``.
    Writes a STATE ENUM (never a command) to app-control.json; the command-locked Windows
    launcher reconciles actual→desired. Behind Access SSO (owner-only)."""
    if room_id != "cyborganic":
        raise HTTPException(status_code=404, detail=f"no app control for room: {room_id}")
    import time

    import hq_stream
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    action = (body or {}).get("action")
    try:
        payload = hq_stream.write_app_control(action, time.time())
    except ValueError:
        raise HTTPException(status_code=400, detail="action must be 'run' or 'stop'")
    return {"ok": True, "control": payload}


@hq_router.get("/room/{room_id}/app")
def room_app_status(room_id: str) -> Dict[str, Any]:
    """The app's actual state for HQ (B3). Reads app-status.json (written by the launcher);
    reports ``controller_offline`` when its heartbeat is stale / the launcher isn't running."""
    if room_id != "cyborganic":
        raise HTTPException(status_code=404, detail=f"no app control for room: {room_id}")
    import time

    import hq_stream
    return {"available": True, **hq_stream.app_status_full(time.time())}


@hq_router.get("/room/{room_id}/stream")
async def room_stream(room_id: str, request: Request) -> StreamingResponse:
    """Live MJPEG view of a room's app (B2, per STREAM.md). On-demand: connecting drives the
    viewer count up (the collector-independent stream controller writes control.json so the
    app starts rendering); disconnecting releases it. Only cyborganic has a stream wired today.

    Frames stay on the shared disk; this Access-gated endpoint is their only exit.
    """
    if room_id != "cyborganic":
        raise HTTPException(status_code=404, detail=f"no live stream for room: {room_id}")
    import hq_stream

    return StreamingResponse(
        hq_stream.mjpeg_generator(request),
        media_type=f"multipart/x-mixed-replace; boundary={hq_stream.BOUNDARY}",
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )


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
