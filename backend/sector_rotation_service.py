"""Shared sector-rotation compute + snapshot service.

Both the API route (:mod:`sector_rotation_routes`) and the daily warming cron
(:mod:`scripts.warm_sector_rotation`) need to do the same thing: run the full
sweep, attach per-constituent contributors, generate the AI assessment, and
persist the result to the disk snapshot. That logic lives here once so the two
entry points can never drift.

The snapshot is the cache that makes the dashboard load instantly: the route
serves it without recomputing, and the cron keeps it warm so a cold page load
never has to run the slow (network-bound, rate-limited) sweep inline.

Everything is exception-wrapped and degrades gracefully:
- the sweep degrades each stream to empty rather than raising,
- contributors degrade to ``None`` if quotes are unavailable,
- the AI assessment degrades to ``None`` if the worker bus is down,
- a snapshot write failure degrades to an in-memory result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    _PT_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tzdata missing
    _PT_TZ = timezone(timedelta(hours=-8))

logger = logging.getLogger(__name__)

# A snapshot older than this is considered stale (a fresh sweep is warranted).
SNAPSHOT_TTL = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Snapshot IO (atomic write, tolerant read) — mirrors portfolio_routes pattern
# ---------------------------------------------------------------------------

def snapshot_path() -> str:
    return os.environ.get(
        "SECTOR_ROTATION_SNAPSHOT_PATH", "/tmp/sector_rotation_latest.json"
    )


def save_snapshot(result: Dict[str, Any]) -> Optional[str]:
    """Atomically persist the latest completed sweep. Best-effort, never raises."""
    try:
        path = snapshot_path()
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
        logger.info("Sector-rotation snapshot written to %s", path)
        return path
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to write sector-rotation snapshot: %s", e)
        return None


def read_snapshot() -> Optional[Dict[str, Any]]:
    """Read the persisted snapshot, or None if absent/unreadable."""
    path = snapshot_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to read sector-rotation snapshot %s: %s", path, e)
        return None


def age_minutes(saved_at: Optional[str]) -> int:
    if not saved_at:
        return 0
    try:
        dt = datetime.fromisoformat(saved_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    except Exception:
        return 0


def is_fresh(saved_at: Optional[str]) -> bool:
    if not saved_at:
        return False
    try:
        dt = datetime.fromisoformat(saved_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) < SNAPSHOT_TTL
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Inputs: portfolio holdings + watchlist (for tagging + contributor flags)
# ---------------------------------------------------------------------------

async def portfolio_holdings_and_watchlist() -> Tuple[List[Any], List[str]]:
    """Best-effort current SnapTrade holdings + watchlist. Degrades to ([], [])."""
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
        logger.info("sector-rotation: holdings/watchlist fetch failed (continuing): %s", e)
    return holdings, watchlist


# ---------------------------------------------------------------------------
# The one compute path used by both the route and the cron
# ---------------------------------------------------------------------------

async def compute_and_store(
    *,
    generate_ai: bool = True,
    with_contributors: bool = True,
    ai_timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the full sweep, attach contributors + AI assessment, persist. Never raises.

    Steps (each independently degrading):
      1. Fetch holdings/watchlist (for sector tagging + contributor portfolio flags).
      2. Run :func:`sector_rotation.run_sector_rotation` in a thread (sync, network-bound).
      3. Run :func:`sector_rotation.constituents.compute_contributors` in a thread
         (sync, rate-limited quote/news fetches) — *who* is pulling each sector.
      4. Generate the LLM assessment (async, via the worker bus) — the daily read.
      5. Save the merged result to the snapshot.

    Returns the merged ``result`` dict (also persisted).
    """
    from sector_rotation import run_sector_rotation

    holdings, watchlist = await portfolio_holdings_and_watchlist()
    loop = asyncio.get_event_loop()

    # 2. Sector-aggregate sweep (the existing 5-stream fusion).
    result = await loop.run_in_executor(
        None, lambda: run_sector_rotation(holdings, watchlist=watchlist)
    )

    # 3. Per-constituent contributors — the new "stocks pulling sectors" layer.
    if with_contributors:
        try:
            from sector_rotation.constituents import compute_contributors

            contributors = await loop.run_in_executor(
                None,
                lambda: compute_contributors(holdings, watchlist=watchlist),
            )
            result["contributors"] = contributors
        except Exception as e:  # noqa: BLE001
            logger.warning("sector-rotation: contributors failed (continuing): %s", e)
            result["contributors"] = None

    # 4. LLM daily assessment — the intelligent read (cached in the snapshot).
    if generate_ai:
        try:
            from sector_rotation.assessment import generate_assessment

            assessment = await generate_assessment(
                result, result.get("contributors"), timeout=ai_timeout
            )
            result["assessment"] = assessment
        except Exception as e:  # noqa: BLE001
            logger.warning("sector-rotation: assessment failed (continuing): %s", e)
            result["assessment"] = None

    # 5. Persist.
    save_snapshot(result)
    return result
