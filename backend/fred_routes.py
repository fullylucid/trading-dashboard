"""
Macro Routes — FastAPI router exposing FRED economic data at /api/macro.

Endpoints:
- GET /api/macro/indicators            — curated headline macro dashboard
- GET /api/macro/treasuries            — Treasury yield curve (FRED constant maturity)
- GET /api/macro/series/{series_id}    — latest value + metadata for any series
- GET /api/macro/series/{series_id}/history — observation history for charting

Backed by fred_client.FredClient. Returns 503 when FRED_API_KEY is unset and
502 on an upstream FRED error so the dashboard can degrade gracefully.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from fred_client import (
    KEY_INDICATORS,
    FredError,
    FredNotConfigured,
    get_fred_client,
)

logger = logging.getLogger(__name__)

macro_router = APIRouter(prefix="/api/macro", tags=["macro"])


def _handle_fred_error(context: str, exc: Exception) -> HTTPException:
    """Map FRED failures onto HTTP errors (503 unconfigured, 502 upstream)."""
    if isinstance(exc, FredNotConfigured):
        return HTTPException(status_code=503, detail="FRED_API_KEY not configured")
    logger.error("%s: %s", context, exc)
    return HTTPException(status_code=502, detail="FRED upstream error")


@macro_router.get("/indicators")
async def get_macro_indicators():
    """Curated headline economic indicators (rates, inflation, labor, growth)."""
    try:
        return await get_fred_client().get_indicators()
    except FredError as e:
        raise _handle_fred_error("Macro indicators error", e)


@macro_router.get("/treasuries")
async def get_macro_treasuries():
    """Treasury yield curve from FRED constant-maturity series."""
    try:
        curve = await get_fred_client().get_treasury_yields()
        return {
            "treasuries": curve,
            "count": len(curve),
            "timestamp": datetime.now().isoformat(),
        }
    except FredError as e:
        raise _handle_fred_error("Macro treasuries error", e)


@macro_router.get("/series/{series_id}")
async def get_macro_series(series_id: str, units: Optional[str] = Query(None)):
    """Latest value (+ change) and metadata for an arbitrary FRED series."""
    try:
        client = get_fred_client()
        latest = await client.get_latest(series_id.upper(), units=units)
        info = await client.get_series_info(series_id.upper())
        return {
            "series_id": series_id.upper(),
            "title": info.get("title") if info else None,
            "units_label": info.get("units") if info else None,
            "frequency": info.get("frequency") if info else None,
            "latest": latest,
            "timestamp": datetime.now().isoformat(),
        }
    except FredError as e:
        raise _handle_fred_error(f"Macro series error ({series_id})", e)


@macro_router.get("/series/{series_id}/history")
async def get_macro_series_history(
    series_id: str,
    observation_start: Optional[str] = Query(
        None, description="YYYY-MM-DD lower bound"
    ),
    limit: int = Query(500, le=10000),
    units: Optional[str] = Query(None),
):
    """Observation history ({date, value}) for charting a FRED series."""
    try:
        points = await get_fred_client().get_series_history(
            series_id.upper(),
            observation_start=observation_start,
            limit=limit,
            units=units,
        )
        return {
            "series_id": series_id.upper(),
            "count": len(points),
            "observations": points,
            "timestamp": datetime.now().isoformat(),
        }
    except FredError as e:
        raise _handle_fred_error(f"Macro series history error ({series_id})", e)


@macro_router.get("/catalog")
async def get_macro_catalog():
    """List the curated indicator series the dashboard knows how to render."""
    return {
        "indicators": KEY_INDICATORS,
        "count": len(KEY_INDICATORS),
    }
