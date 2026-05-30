"""Sector-rotation API routes (Phase 2.5).

Exposes the daily sector-rotation sweep at ``GET /api/sector-rotation``. The
sweep (:func:`sector_rotation.run_sector_rotation`) fans out across five free
data streams (price/RRG, SEC Form-4 smart money, Finnhub news, earnings/FRED
catalysts, congressional/USAspending policy), which is slow and rate-limited, so
this router caches aggressively:

- **Disk snapshot** (the same atomic-write pattern as ``portfolio_routes``):
  the latest completed sweep is persisted to ``SECTOR_ROTATION_SNAPSHOT_PATH``
  so the dashboard renders instantly on mount without kicking off a fresh sweep.
- **Daily freshness**: a snapshot is considered fresh for ``_SNAPSHOT_TTL`` (24h
  by default). A request with a stale/absent snapshot computes a new sweep in a
  thread (the sweep is sync + network-bound) and persists it. The daily digest
  cron also refreshes the snapshot out-of-band.

Everything here is additive and exception-wrapped: the sweep never raises (it
degrades each stream to empty), and a snapshot read/write failure degrades to a
live compute rather than a 500.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

try:
    from zoneinfo import ZoneInfo
    _PT_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tzdata missing
    _PT_TZ = timezone(timedelta(hours=-8))

logger = logging.getLogger(__name__)

sector_rotation_router = APIRouter(prefix="/api/sector-rotation", tags=["sector-rotation"])

# Daily refresh: a snapshot older than this is recomputed on demand.
_SNAPSHOT_TTL = timedelta(hours=24)
# Guard so concurrent requests don't kick off N parallel sweeps at once.
_compute_lock = asyncio.Lock()


def _snapshot_path() -> str:
    return os.environ.get(
        "SECTOR_ROTATION_SNAPSHOT_PATH", "/tmp/sector_rotation_latest.json"
    )


def _save_snapshot(result: Dict[str, Any]) -> Optional[str]:
    """Atomically persist the latest completed sweep. Best-effort, never raises.

    Mirrors ``portfolio_routes._save_scan_snapshot``: write to a temp file in the
    target dir then ``os.replace`` so a reader never sees a half-written file.
    """
    try:
        path = _snapshot_path()
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        now_utc = datetime.now(timezone.utc)
        try:
            now_pt = now_utc.astimezone(_PT_TZ)
        except Exception:
            now_pt = now_utc
        payload = {
            "saved_at": now_utc.isoformat(),
            "saved_at_pt": now_pt.isoformat(),
            "result": result,
        }
        fd, tmp = tempfile.mkstemp(
            prefix=".sector_rotation_latest.", suffix=".json", dir=parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, default=str)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        logger.info(f"Sector-rotation snapshot written to {path}")
        return path
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to write sector-rotation snapshot: {e}")
        return None


def _read_snapshot() -> Optional[Dict[str, Any]]:
    """Read the persisted snapshot, or None if absent/unreadable."""
    path = _snapshot_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to read sector-rotation snapshot {path}: {e}")
        return None


def _age_minutes(saved_at: Optional[str]) -> int:
    if not saved_at:
        return 0
    try:
        dt = datetime.fromisoformat(saved_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    except Exception:
        return 0


def _is_fresh(saved_at: Optional[str]) -> bool:
    if not saved_at:
        return False
    try:
        dt = datetime.fromisoformat(saved_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) < _SNAPSHOT_TTL
    except Exception:
        return False


async def _portfolio_holdings_and_watchlist() -> tuple[List[Any], List[str]]:
    """Best-effort: current SnapTrade holdings + watchlist for sector tagging.

    Holdings feed ``map_to_companies`` (tag each holding by its sector's rotation
    status) and seed the per-ticker SEC/Finnhub smart-money scan universe. Any
    failure degrades to empty lists — the sweep still runs over the 11 ETFs.
    """
    holdings: List[Any] = []
    watchlist: List[str] = []
    try:
        from snaptrade_portfolio import get_portfolio_instance

        portfolio = await get_portfolio_instance()
        positions = await portfolio.get_positions()
        for p in positions or []:
            sym = str(p.get("symbol") or "").upper().strip()
            if sym:
                holdings.append({"symbol": sym})
        try:
            wl = await portfolio.get_watchlist()
            for w in wl or []:
                sym = str((w.get("symbol") if isinstance(w, dict) else w) or "").upper().strip()
                if sym:
                    watchlist.append(sym)
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        logger.info(f"sector-rotation: holdings/watchlist fetch failed (continuing): {e}")
    return holdings, watchlist


async def _compute_sweep() -> Dict[str, Any]:
    """Run the full sweep (off the event loop) and persist the snapshot.

    ``run_sector_rotation`` is synchronous + network-bound, so it runs in a
    thread to avoid blocking the FastAPI event loop. Never raises.
    """
    from sector_rotation import run_sector_rotation

    holdings, watchlist = await _portfolio_holdings_and_watchlist()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: run_sector_rotation(holdings, watchlist=watchlist)
    )
    _save_snapshot(result)
    return result


@sector_rotation_router.get("")
@sector_rotation_router.get("/")
async def get_sector_rotation(
    refresh: bool = Query(False, description="Bypass the daily snapshot and recompute"),
) -> Any:
    """Return the latest sector-rotation sweep.

    Serves the persisted snapshot when it is fresh (<24h) so the dashboard loads
    instantly. When the snapshot is stale, absent, or ``refresh=true``, recomputes
    the sweep (in a thread, network-bound), persists it, and returns it. The
    response always carries ``saved_at`` / ``age_minutes`` / ``cached`` so the UI
    can show data freshness.
    """
    snapshot = None if refresh else _read_snapshot()
    if snapshot is not None and _is_fresh(snapshot.get("saved_at")):
        return {
            "saved_at": snapshot.get("saved_at"),
            "saved_at_pt": snapshot.get("saved_at_pt"),
            "age_minutes": _age_minutes(snapshot.get("saved_at")),
            "cached": True,
            "result": snapshot.get("result"),
        }

    # Stale / missing / forced: recompute (single-flight via the lock).
    async with _compute_lock:
        # Re-check after acquiring the lock: a concurrent request may have just
        # refreshed the snapshot while we waited.
        if not refresh:
            snapshot = _read_snapshot()
            if snapshot is not None and _is_fresh(snapshot.get("saved_at")):
                return {
                    "saved_at": snapshot.get("saved_at"),
                    "saved_at_pt": snapshot.get("saved_at_pt"),
                    "age_minutes": _age_minutes(snapshot.get("saved_at")),
                    "cached": True,
                    "result": snapshot.get("result"),
                }
        try:
            result = await _compute_sweep()
        except Exception as e:  # noqa: BLE001 - run_sector_rotation shouldn't raise, but be safe
            logger.error(f"sector-rotation sweep failed: {e}", exc_info=True)
            # Last resort: serve a stale snapshot if we have one.
            stale = _read_snapshot()
            if stale is not None:
                return {
                    "saved_at": stale.get("saved_at"),
                    "saved_at_pt": stale.get("saved_at_pt"),
                    "age_minutes": _age_minutes(stale.get("saved_at")),
                    "cached": True,
                    "stale": True,
                    "result": stale.get("result"),
                }
            return JSONResponse(
                status_code=503,
                content={"error": "sector-rotation sweep unavailable"},
            )

    now_utc = datetime.now(timezone.utc).isoformat()
    return {
        "saved_at": now_utc,
        "age_minutes": 0,
        "cached": False,
        "result": result,
    }


@sector_rotation_router.get("/latest")
async def get_sector_rotation_latest() -> Any:
    """Return only the persisted snapshot (no compute). 404 if none exists yet.

    Lets the dashboard render the last sweep instantly on mount without ever
    triggering a fresh (slow) sweep; the daily cron keeps the snapshot warm.
    """
    snapshot = _read_snapshot()
    if snapshot is None:
        return JSONResponse(
            status_code=404, content={"error": "no sector-rotation snapshot available yet"}
        )
    return {
        "saved_at": snapshot.get("saved_at"),
        "saved_at_pt": snapshot.get("saved_at_pt"),
        "age_minutes": _age_minutes(snapshot.get("saved_at")),
        "cached": True,
        "result": snapshot.get("result"),
    }
