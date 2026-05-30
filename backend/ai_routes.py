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


def _trim(ctx: Any, limit: int = 4000) -> str:
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
    prompt = _build_prompt(kind, req.context or {}, req.symbol)
    try:
        text = await agent_bridge.run_agent_job(prompt, kind="data")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"ai/explain[{kind}] failed: {e}")
        raise HTTPException(status_code=503, detail="AI explanation failed")

    if not text or not text.strip():
        raise HTTPException(status_code=503, detail="AI explanation unavailable (busy or timed out)")
    return {"kind": kind, "symbol": req.symbol, "text": text.strip(), "model": MODEL_LABEL}
