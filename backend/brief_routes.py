"""
Crack-a-Dawn brief API — serves the morning briefs to the dashboard.

Briefs are written by the box cron (crack_a_dawn.run) as {date}.json under the
briefs dir, which is bind-mounted read-only into the backend container at /briefs.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

brief_router = APIRouter(prefix="/api/brief", tags=["crack-a-dawn"])

BRIEFS_DIR = os.getenv("BRIEFS_DIR", "/briefs")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _list_dates() -> List[str]:
    try:
        files = os.listdir(BRIEFS_DIR)
    except FileNotFoundError:
        return []
    dates = sorted(
        (f[:-5] for f in files if f.endswith(".json") and _DATE_RE.match(f[:-5])),
        reverse=True,
    )
    return dates


def _load(date: str) -> Dict[str, Any]:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="bad date format (YYYY-MM-DD)")
    path = os.path.join(BRIEFS_DIR, f"{date}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="no brief for that date")
    with open(path) as f:
        return json.load(f)


@brief_router.get("/dates")
async def brief_dates() -> Dict[str, List[str]]:
    """All dates with a brief, newest first — drives the archive calendar."""
    return {"dates": _list_dates()}


@brief_router.get("/latest")
async def brief_latest() -> Dict[str, Any]:
    dates = _list_dates()
    if not dates:
        raise HTTPException(status_code=404, detail="no briefs yet")
    return _load(dates[0])


@brief_router.get("/{date}")
async def brief_for_date(date: str) -> Dict[str, Any]:
    return _load(date)
