"""
Options Strategist API routes.

Serves the live-data layer for the frontend strategy lab (spot / IV /
expirations / chains) and the deterministic opportunity snapshot + Claude
prompt for the WSL2 opportunity finder.

Design split (per product decision): Python computes the numbers
deterministically here; the actual ranking/strategy reasoning is done by Claude
on the user's WSL2 box. The frontend takes the prompt returned by
/api/options/opportunity-prompt and submits it through the existing agent
bridge (kind="scan"), so this router stays unauthenticated and side-effect-free
— it never enqueues jobs itself.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from options import chains
from options import discovery

logger = logging.getLogger(__name__)

options_router = APIRouter(prefix="/api/options", tags=["options"])


@options_router.get("/snapshot/{symbol}")
async def get_snapshot(symbol: str) -> Dict[str, Any]:
    """Live scenario data for the strategy lab: spot, ATM IV, risk-free rate,
    realized vol, IV-rank proxy, and the expirations table (DTE + expected move).
    Populates the header so the user trades real, timeframe-aware numbers."""
    snap = await asyncio.to_thread(chains.get_snapshot, symbol)
    if snap.get("error"):
        raise HTTPException(status_code=404, detail=f"{symbol}: {snap['error']}")
    return snap


@options_router.get("/chain/{symbol}")
async def get_chain(
    symbol: str,
    expiration: str = Query(..., description="Expiration date as YYYY-MM-DD"),
) -> Dict[str, Any]:
    """Listed calls/puts for one expiration, with per-row IV and delta."""
    chain = await asyncio.to_thread(chains.get_chain, symbol, expiration)
    if chain.get("error"):
        raise HTTPException(status_code=404, detail=f"{symbol} {expiration}: {chain['error']}")
    return chain


@options_router.get("/universe")
async def get_universe(
    include_market_scan: bool = Query(True),
) -> Dict[str, List[str]]:
    """The candidate universe tagged by source (holdings / watchlist / market scan)."""
    return await discovery.build_universe(include_market_scan=include_market_scan)


class OpportunityRequest(BaseModel):
    horizon_days: int = Field(30, ge=1, le=365, description="Trading horizon in calendar days")
    outlook: str = Field("any", description="bullish | bearish | neutral | volatile | any")
    symbols: Optional[List[str]] = Field(None, description="Extra tickers to include")
    include_market_scan: bool = Field(True, description="Include curated market-scan discoveries")
    top_n: int = Field(12, ge=1, le=30, description="Max candidates to hand Claude")


@options_router.post("/opportunity-prompt")
async def opportunity_prompt(req: OpportunityRequest) -> Dict[str, Any]:
    """Build the deterministic snapshot and the Claude prompt.

    Returns both `snapshot` (rendered inline in the UI so the user sees the
    computed data immediately) and `prompt` (which the frontend submits to the
    WSL2 Claude worker via the agent bridge for ranking + strategy reasoning).
    """
    snapshot = await discovery.build_snapshot(
        req.horizon_days,
        extra_symbols=req.symbols,
        include_market_scan=req.include_market_scan,
    )
    if not snapshot.get("candidates"):
        raise HTTPException(
            status_code=503,
            detail="No option snapshots could be built (market data unavailable). Try again shortly.",
        )
    prompt = discovery.build_claude_prompt(
        snapshot, req.outlook, req.horizon_days, top_n=req.top_n
    )
    return {"snapshot": snapshot, "prompt": prompt, "outlook": req.outlook, "horizon_days": req.horizon_days}
