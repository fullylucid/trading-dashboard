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

from fastapi import APIRouter

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

hq_router = APIRouter(prefix="/api/hq", tags=["hq"])
logger = logging.getLogger("hq_routes")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FLEET_KEY = "hq:fleet"

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


@hq_router.get("/fleet")
def fleet() -> Dict[str, Any]:
    """The whole-fleet snapshot: rooms, heads (status/current/branch/git), activity, memory.

    Read-only passthrough of Redis ``hq:fleet`` (built host-side by hq_collector.py). Returns
    ``{"available": false}`` if the collector hasn't run yet / the key expired, so the UI can
    show a clean "collector offline" state instead of erroring.
    """
    r = _r()
    if r is None:
        return {"available": False}
    raw = r.get(FLEET_KEY)
    if not raw:
        return {"available": False}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"available": False}
    data["available"] = True
    return data
