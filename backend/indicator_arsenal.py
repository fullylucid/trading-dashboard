"""Indicator "arsenal" — a Redis-backed library of APPROVED indicator specs.

The acceptance sink for the indicator-spec engine: a spec a human (or the charting
scout, later) has blessed is saved here, and the Charts UI offers saved specs as
ready-to-add indicators. Specs are validated through :mod:`indicator_spec` on the
way in, so only well-formed, bounded specs ever land in the library.

Storage: one Redis hash ``indicator:arsenal``, field = item id, value = JSON of
``{id, name, short_name, pane, source, tags, created_at, spec}`` where ``spec`` is
the NORMALIZED spec. Mirrors the sync-redis, graceful-degradation pattern used by
``fintube/store.py`` (returns empty / False when Redis is down rather than raising).
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

from indicator_spec import SpecError, validate_spec

logger = logging.getLogger("indicator.arsenal")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

ARSENAL_KEY = "indicator:arsenal"
MAX_ITEMS = 200

_client: Optional["redis.Redis"] = None


def _r() -> Optional["redis.Redis"]:
    global _client
    if redis is None:
        return None
    if _client is None:
        try:
            _client = redis.from_url(REDIS_URL, decode_responses=True)
            _client.ping()
        except Exception as e:  # noqa: BLE001
            logger.warning("indicator arsenal redis unavailable: %s", e)
            _client = None
    return _client


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:32] or "indicator"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_items() -> List[Dict[str, Any]]:
    """All saved arsenal items, newest first. Empty list if Redis is down/empty."""
    c = _r()
    if c is None:
        return []
    try:
        raw = c.hgetall(ARSENAL_KEY) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("arsenal list failed: %s", e)
        return []
    items: List[Dict[str, Any]] = []
    for v in raw.values():
        try:
            items.append(json.loads(v))
        except (json.JSONDecodeError, TypeError):
            continue
    items.sort(key=lambda it: it.get("created_at", ""), reverse=True)
    return items


def get_item(item_id: str) -> Optional[Dict[str, Any]]:
    c = _r()
    if c is None:
        return None
    try:
        raw = c.hget(ARSENAL_KEY, item_id)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def save_item(
    spec: Any,
    source: str = "manual",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Validate `spec` and persist it as a new arsenal item. Raises on bad input.

    Raises :class:`SpecError` if the spec is invalid, ``RuntimeError`` if Redis is
    unavailable or the library is full. Returns the stored item.
    """
    normalized = validate_spec(spec)  # raises SpecError with .errors
    c = _r()
    if c is None:
        raise RuntimeError("arsenal storage unavailable")
    try:
        if c.hlen(ARSENAL_KEY) >= MAX_ITEMS:
            raise RuntimeError(f"arsenal full (max {MAX_ITEMS})")
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 — hlen failure shouldn't block a save
        pass

    item_id = f"{_slug(normalized['name'])}-{uuid.uuid4().hex[:6]}"
    item = {
        "id": item_id,
        "name": normalized["name"],
        "short_name": normalized["short_name"],
        "pane": normalized["pane"],
        "source": (source or "manual")[:32],
        "tags": [str(t)[:24] for t in (tags or [])][:8],
        "created_at": _now(),
        "spec": normalized,
    }
    try:
        c.hset(ARSENAL_KEY, item_id, json.dumps(item))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"arsenal save failed: {e}") from None
    return item


def delete_item(item_id: str) -> bool:
    c = _r()
    if c is None:
        return False
    try:
        return bool(c.hdel(ARSENAL_KEY, item_id))
    except Exception:  # noqa: BLE001
        return False
