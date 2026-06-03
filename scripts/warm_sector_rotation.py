#!/usr/bin/env python3
"""Warm the sector-rotation snapshot + daily AI assessment (box cron / systemd).

Runs the full sweep out-of-band so the dashboard's ``/api/sector-rotation/latest``
read is always instant. Intended to fire once a trading day, shortly after
crack-a-dawn, via ``worker/sector-rotation.timer``:

    python3 scripts/warm_sector_rotation.py [--no-ai]

It computes the sweep + per-constituent contributors and (unless ``--no-ai``)
asks the local Opus worker for the daily read, then persists everything to
``SECTOR_ROTATION_SNAPSHOT_PATH`` (default ``/tmp/sector_rotation_latest.json``).

Degrades gracefully end to end: a missing FRED/Finnhub key, an offline worker
bus, or a stream failure never aborts the run — the snapshot is written with
whatever computed. Exit code is 0 on a written snapshot, 1 only on a hard failure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Make the backend package importable whether invoked from repo root or scripts/.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("warm_sector_rotation")


async def _maybe_init_bus() -> bool:
    """Best-effort connect to the agent-bridge Redis bus so the AI read can run.

    Returns True if the worker bus is reachable. On any failure we log and
    continue — ``generate_assessment`` already degrades to None when the bus is
    down, so the snapshot is still written (just without the LLM read).
    """
    try:
        import agent_bridge

        await agent_bridge.startup_event()
        logger.info("agent bus connected; AI assessment enabled")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("agent bus unavailable; AI assessment will be skipped: %s", e)
        return False


async def _run(generate_ai: bool) -> int:
    from sector_rotation_service import compute_and_store, snapshot_path

    bus_ok = await _maybe_init_bus() if generate_ai else False
    result = await compute_and_store(
        generate_ai=generate_ai and bus_ok,
        with_contributors=True,
    )

    if generate_ai and bus_ok:
        try:
            import agent_bridge

            await agent_bridge.shutdown_event()
        except Exception:  # noqa: BLE001
            pass

    n_sectors = len((result or {}).get("rotation") or {})
    contrib = (result or {}).get("contributors") or {}
    assessment = (result or {}).get("assessment") or {}
    logger.info(
        "sweep done: %d sectors scored, %d/%d constituent quotes, AI read=%s -> %s",
        n_sectors,
        contrib.get("quotes_ok", 0),
        contrib.get("quotes_tried", 0),
        "yes" if assessment.get("short") else "no",
        snapshot_path(),
    )
    return 0 if n_sectors > 0 or contrib.get("quotes_ok", 0) > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Warm the sector-rotation snapshot.")
    ap.add_argument(
        "--no-ai",
        action="store_true",
        help="skip the LLM daily assessment (data-only warm)",
    )
    args = ap.parse_args()
    try:
        return asyncio.run(_run(generate_ai=not args.no_ai))
    except Exception as e:  # noqa: BLE001
        logger.error("warm run failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
