"""Sector-rotation API routes (Phase 2.5 + intelligence overhaul).

Exposes the daily sector-rotation sweep. The sweep
(:func:`sector_rotation_service.compute_and_store`) fans out across five free
data streams (price/RRG, SEC Form-4 smart money, Finnhub news, earnings/FRED
catalysts, congressional/USAspending policy), attaches per-constituent
contributors (which *stocks* pull each sector), and an LLM daily assessment —
all slow and rate-limited, so this router never computes inline on the hot path.

Endpoints
---------
- ``GET /api/sector-rotation/latest`` — **instant, non-blocking**: returns the
  persisted snapshot (or ``result: null`` if none yet) plus a ``computing`` flag.
  This is what the dashboard calls on mount, so a cold load never hangs on a sweep.
- ``POST /api/sector-rotation/refresh`` — kick a background recompute (single
  flight) and return immediately. The UI polls ``/latest`` until it lands.
- ``GET /api/sector-rotation`` — **blocking** compute-or-serve, kept for the cron
  / manual refresh / back-compat. Serves a fresh snapshot, else computes inline.

Caching: the latest completed sweep is persisted to ``SECTOR_ROTATION_SNAPSHOT_PATH``
and considered fresh for 24h. The warming cron keeps it warm out-of-band so the
``computing`` path is rarely hit by a user.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from sector_rotation_service import (
    age_minutes,
    compute_and_store,
    is_fresh,
    read_snapshot,
)

logger = logging.getLogger(__name__)

sector_rotation_router = APIRouter(prefix="/api/sector-rotation", tags=["sector-rotation"])

# Single-flight: serialize inline computes; track the background refresh so the
# non-blocking endpoints can report progress without launching duplicate sweeps.
_compute_lock = asyncio.Lock()
_refresh_task: Optional["asyncio.Task[Any]"] = None


def _is_computing() -> bool:
    return _refresh_task is not None and not _refresh_task.done()


def _envelope(snapshot: Dict[str, Any], *, stale: bool = False) -> Dict[str, Any]:
    saved_at = snapshot.get("saved_at")
    return {
        "saved_at": saved_at,
        "saved_at_pt": snapshot.get("saved_at_pt"),
        "age_minutes": age_minutes(saved_at),
        "cached": True,
        "stale": stale,
        "result": snapshot.get("result"),
    }


async def _background_refresh() -> None:
    """Run a full compute+store under the lock (used by POST /refresh)."""
    async with _compute_lock:
        try:
            await compute_and_store(generate_ai=True, with_contributors=True)
        except Exception as e:  # noqa: BLE001 - compute_and_store shouldn't raise
            logger.error("sector-rotation background refresh failed: %s", e, exc_info=True)


@sector_rotation_router.get("/latest")
async def get_sector_rotation_latest() -> Any:
    """Instant snapshot read — never computes. Always 200.

    Returns the persisted snapshot (with ``stale`` set when older than the TTL),
    or ``result: null`` when no sweep has ever run. ``computing`` reflects whether
    a background refresh is in flight, so the UI can show a spinner and poll.
    """
    snapshot = read_snapshot()
    if snapshot is None:
        return {
            "saved_at": None,
            "age_minutes": None,
            "cached": False,
            "stale": False,
            "computing": _is_computing(),
            "result": None,
        }
    env = _envelope(snapshot, stale=not is_fresh(snapshot.get("saved_at")))
    env["computing"] = _is_computing()
    return env


@sector_rotation_router.post("/refresh")
async def refresh_sector_rotation() -> Any:
    """Kick a background sweep (single flight) and return immediately (202).

    Idempotent: if a refresh is already running, reports ``already_running`` and
    does not start a second. The client polls ``GET /latest`` to pick up the
    result when ``computing`` flips back to false.
    """
    global _refresh_task
    if _is_computing():
        return JSONResponse(
            status_code=202,
            content={"computing": True, "already_running": True},
        )
    _refresh_task = asyncio.create_task(_background_refresh())
    return JSONResponse(
        status_code=202,
        content={"computing": True, "already_running": False},
    )


@sector_rotation_router.get("")
@sector_rotation_router.get("/")
async def get_sector_rotation(
    refresh: bool = Query(False, description="Bypass the daily snapshot and recompute"),
) -> Any:
    """Blocking compute-or-serve (cron / manual / back-compat).

    Serves the persisted snapshot when fresh (<24h). When stale, absent, or
    ``refresh=true``, recomputes inline (network-bound, may take ~30-60s),
    persists, and returns it. The dashboard should prefer ``/latest`` + ``/refresh``.
    """
    snapshot = None if refresh else read_snapshot()
    if snapshot is not None and is_fresh(snapshot.get("saved_at")):
        return _envelope(snapshot)

    async with _compute_lock:
        # Re-check after acquiring the lock: a concurrent request/background
        # refresh may have just persisted a fresh snapshot while we waited.
        if not refresh:
            snapshot = read_snapshot()
            if snapshot is not None and is_fresh(snapshot.get("saved_at")):
                return _envelope(snapshot)
        try:
            result = await compute_and_store(generate_ai=True, with_contributors=True)
        except Exception as e:  # noqa: BLE001 - shouldn't raise, but be safe
            logger.error("sector-rotation sweep failed: %s", e, exc_info=True)
            stale = read_snapshot()
            if stale is not None:
                return _envelope(stale, stale=True)
            return JSONResponse(
                status_code=503,
                content={"error": "sector-rotation sweep unavailable"},
            )

    return {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "age_minutes": 0,
        "cached": False,
        "stale": False,
        "result": result,
    }
