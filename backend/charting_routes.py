"""Charting-ideas scout HTTP surface.

Thin router over :mod:`charting_scout`. Open like the other dashboard data routes.

- ``GET  /api/charting/sources``          -> available source adapters + impl status.
- ``GET  /api/charting/ideas``            -> staged idea cards (newest first).
- ``POST /api/charting/scout``            -> kick a scout run in the background
  (``{sources?, max?}``); guarded against concurrent runs.
- ``POST /api/charting/ideas/{id}/accept``-> promote an idea's validated spec into
  the arsenal (``{tags?}``).
- ``DELETE /api/charting/ideas/{id}``     -> drop a staged idea.
"""
import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Path as PathParam, Request

import charting_scout as _scout
from indicator_spec import SpecError

logger = logging.getLogger(__name__)

charting_router = APIRouter(prefix="/api/charting", tags=["charting"])

_scout_running = False


@charting_router.get("/sources")
def sources() -> dict:
    return {
        "sources": [
            {"name": name, "implemented": meta["implemented"]}
            for name, meta in _scout.SOURCES.items()
        ]
    }


@charting_router.get("/ideas")
def ideas(limit: int = 80) -> dict:
    return {"ideas": _scout.list_ideas(limit=max(1, min(limit, _scout.IDEAS_MAX)))}


async def _run_scout_guarded(sources_list, max_ideas) -> None:
    global _scout_running
    if _scout_running:
        return
    _scout_running = True
    try:
        result = await _scout.run_scout(sources=sources_list, max_ideas=max_ideas)
        logger.info("charting scout finished: %s", result)
    except Exception as e:  # noqa: BLE001
        logger.warning("charting scout run failed: %s", e)
    finally:
        _scout_running = False


@charting_router.post("/scout")
async def scout(request: Request, background: BackgroundTasks) -> dict:
    if _scout_running:
        return {"status": "already running"}
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    sources_list = data.get("sources")
    try:
        max_ideas = int(data.get("max", 12))
    except (TypeError, ValueError):
        max_ideas = 12
    max_ideas = max(1, min(max_ideas, 50))
    background.add_task(_run_scout_guarded, sources_list, max_ideas)
    return {"status": "started", "max": max_ideas}


@charting_router.post("/ideas/{idea_id}/accept")
async def accept(request: Request, idea_id: str = PathParam(...)) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    tags = data.get("tags") if isinstance(data, dict) else None
    try:
        return _scout.accept_idea(idea_id, tags=tags)
    except KeyError:
        raise HTTPException(status_code=404, detail="Idea not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except SpecError as e:
        raise HTTPException(status_code=400, detail={"errors": e.errors}) from None
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None


@charting_router.delete("/ideas/{idea_id}")
def delete(idea_id: str = PathParam(...)) -> dict:
    return {"deleted": _scout.delete_idea(idea_id)}
