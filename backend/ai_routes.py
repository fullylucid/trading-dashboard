"""
AI Explain Routes — on-demand Claude (free local Opus 4.8 via the agent-bridge)
explanations for dashboard datapoints.

One reusable endpoint instead of a bespoke Claude call per widget. The browser
POSTs a `kind` + context blob; the local worker writes a short, concrete
explanation; we return the text synchronously. Auth reuses the agent session
cookie (same as the chart AI-read). Everything degrades gracefully — a 503 if
the bus is down or busy, so widgets just hide the blurb.

Surfaces (kind): alert | regime | sector | generic. Add a prompt builder to
extend; no per-widget backend code needed.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    import agent_bridge  # type: ignore
    from agent_bridge import require_session  # type: ignore
except Exception:  # noqa: BLE001
    try:
        from backend import agent_bridge  # type: ignore
        from backend.agent_bridge import require_session  # type: ignore
    except Exception:  # noqa: BLE001
        agent_bridge = None  # type: ignore

        def require_session(request):  # type: ignore
            raise HTTPException(status_code=503, detail="AI explain unavailable")


router = APIRouter(prefix="/api/ai", tags=["ai"])

MODEL_LABEL = "opus-4.8 (agent-bridge)"


class ExplainRequest(BaseModel):
    kind: str = "generic"            # alert | regime | sector | generic
    context: Dict[str, Any] = {}
    symbol: Optional[str] = None


def _trim(ctx: Any, limit: int = 6000) -> str:
    return json.dumps(ctx, indent=2, default=str)[:limit]


def _build_prompt(kind: str, context: Dict[str, Any], symbol: Optional[str]) -> str:
    ctx = _trim(context)
    sym = f" for {symbol}" if symbol else ""
    if kind == "alert":
        return (
            f"You are a terse trading-desk analyst. In 2-3 sentences, explain why this "
            f"alert{sym} fired and what it means for the position — name the specific "
            f"factors driving it and the direction. No hedging, no disclaimers.\n\n"
            f"ALERT DATA:\n{ctx}"
        )
    if kind == "regime":
        return (
            f"You are a terse market strategist. In 2-3 sentences, explain the current "
            f"market regime and what it implies for position sizing and stop placement. "
            f"Concrete, no disclaimers.\n\nREGIME DATA:\n{ctx}"
        )
    if kind == "sector":
        return (
            f"You are a terse sector strategist. In 1-2 sentences, give a headline read on "
            f"what is rotating IN vs OUT and why it matters for a swing trader — cite the "
            f"strongest movers by name. No disclaimers.\n\nSECTOR ROTATION DATA:\n{ctx}"
        )
    if kind == "chart":
        question = (context.get("question") or "").strip()
        if question:
            return (
                f"You are a sharp trading-desk chart copilot. Answer the trader's QUESTION about "
                f"{symbol or 'this chart'} using the chart context below (precomputed, no-look-ahead "
                f"signals + levels, plus the indicators currently on their screen). Be concrete — cite "
                f"the actual numbers (price, RSI/MACD, support/resistance, Fibonacci). 3-6 sentences, no "
                f"hedging, no disclaimers. If the context can't answer it, say so in one line.\n\n"
                f"QUESTION: {question}\n\nCHART CONTEXT:\n{ctx}"
            )
        return (
            f"You are a sharp trading-desk chart copilot. Give a concise read of {symbol or 'this chart'}: "
            f"trend/regime, momentum (RSI/MACD/divergence), relative strength, and the key levels (nearest "
            f"support/resistance + most relevant Fibonacci). Say where price sits in its range, then end with "
            f"a one-line bias (bullish / neutral / bearish) and the invalidation level. Cite real numbers. "
            f"4-7 sentences, no hedging, no disclaimers.\n\nCHART CONTEXT:\n{ctx}"
        )
    return (
        f"In 2-3 sentences, explain the following trading data{sym} concretely for a swing "
        f"trader. No hedging, no disclaimers.\n\nDATA:\n{ctx}"
    )


@router.post("/explain")
async def explain(req: ExplainRequest, request: Request) -> Dict[str, Any]:
    """Return a short Claude explanation of a dashboard datapoint."""
    require_session(request)
    if agent_bridge is None:
        raise HTTPException(status_code=503, detail="AI explain unavailable")

    kind = (req.kind or "generic").lower()
    context = dict(req.context or {})
    # Chart copilot: enrich with real server-computed TA (signals / S-R / Fibonacci),
    # reusing the same builder as the chart AI-read so the model reasons from real numbers.
    if kind == "chart" and req.symbol:
        try:
            import chart_routes  # lazy; avoids import cost on non-chart calls
            ta = await asyncio.to_thread(chart_routes._build_ta_context, req.symbol)
            context = {**context, "ta": ta}
        except Exception as e:  # noqa: BLE001
            logger.debug(f"ai/explain[chart]: TA enrich failed: {e}")
    prompt = _build_prompt(kind, context, req.symbol)
    try:
        text = await agent_bridge.run_agent_job(prompt, kind="data")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"ai/explain[{kind}] failed: {e}")
        raise HTTPException(status_code=503, detail="AI explanation failed")

    if not text or not text.strip():
        raise HTTPException(status_code=503, detail="AI explanation unavailable (busy or timed out)")
    return {"kind": kind, "symbol": req.symbol, "text": text.strip(), "model": MODEL_LABEL}
