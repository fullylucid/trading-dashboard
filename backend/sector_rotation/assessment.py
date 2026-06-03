"""LLM daily assessment of the sector-rotation sweep (the "intelligent read").

Everything else in this package is mechanical: numbers in, numbers out. This
module is the one place that asks a model to *interpret* the fused picture —
where capital is rotating, which named stocks are pulling each sector, and what
it means for the book — in plain language.

It runs **once per day** (in the warming cron / on an explicit refresh), not on
every page load, and the result is cached inside the snapshot under
``result["assessment"]``. The model is the free local Opus worker reached through
:func:`agent_bridge.run_agent_job` (Redis job bus, ``kind="data"``). If the bus
is down or the model misbehaves, every path degrades to ``None`` and the UI just
shows the mechanical headline — the assessment is strictly additive.

The model is asked for a small JSON object::

    {"short": "<3-5 sentence rotation read>",
     "full":  "<markdown analyst briefing>"}

so the frontend can show the concise read by default and the full briefing in a
"deep dive" expander.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# Keep the prompt payload small: only the most decisive rows reach the model.
_MAX_SECTORS = 6
_MAX_MOVERS = 4


def _round(v: Any, n: int = 1) -> Any:
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def _brief_movers(rows: Optional[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Compact a leaders_up/leaders_down list for the prompt."""
    out: List[Dict[str, Any]] = []
    for r in (rows or [])[:_MAX_MOVERS]:
        item: Dict[str, Any] = {
            "symbol": r.get("symbol"),
            "pct": _round(r.get("pct_change")),
            "contribution": _round(r.get("contribution"), 3),
        }
        if r.get("in_portfolio"):
            item["held"] = True
        news = r.get("news")
        if isinstance(news, dict) and news.get("top_headline"):
            item["news"] = {
                "tone": news.get("label"),
                "headline": str(news.get("top_headline"))[:160],
            }
        out.append(item)
    return out


def build_payload(
    result: Mapping[str, Any],
    contributors: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """PURE: distill the sweep + contributors into a compact dict for the model.

    Pulls the rotating-in/out leaders, their named constituent drivers, breadth,
    and the portfolio tailwinds/risks. Kept small and stable so the prompt is
    cheap and the model focuses on interpretation, not parsing.
    """
    rotation = result.get("rotation") or {}
    summary = result.get("summary") or {}
    companies = result.get("companies") or {}
    market = result.get("market") or {}
    by_etf = (contributors or {}).get("by_etf") or {}

    rows = list(rotation.values()) if isinstance(rotation, Mapping) else []
    ranked = sorted(
        rows,
        key=lambda r: abs(float(r.get("rotation_score") or 0.0)),
        reverse=True,
    )[:_MAX_SECTORS]

    sectors: List[Dict[str, Any]] = []
    for r in ranked:
        etf = r.get("etf")
        contrib = by_etf.get(etf) if isinstance(by_etf, Mapping) else None
        entry: Dict[str, Any] = {
            "sector": r.get("sector"),
            "etf": etf,
            "status": r.get("status"),
            "score": _round(r.get("rotation_score")),
            "confidence": _round(r.get("confidence"), 0),
            "phase": r.get("phase"),
            "drivers": {k: _round(v, 1) for k, v in (r.get("components") or {}).items()
                        if v is not None},
        }
        if isinstance(contrib, Mapping):
            entry["breadth"] = contrib.get("breadth")
            entry["leaders_up"] = _brief_movers(contrib.get("leaders_up"))
            entry["leaders_down"] = _brief_movers(contrib.get("leaders_down"))
        sectors.append(entry)

    return {
        "benchmark": market.get("benchmark"),
        "headline_counts": {
            "rotating_in": len(summary.get("rotating_in") or []),
            "rotating_out": len(summary.get("rotating_out") or []),
            "alerts": len(summary.get("alerts") or []),
        },
        "sectors": sectors,
        "portfolio": {
            "tailwinds": (companies.get("tailwinds") or [])[:12],
            "risks": (companies.get("risks") or [])[:12],
        },
        "sources_ok": result.get("sources_ok") or summary.get("sources_ok") or {},
    }


_SYSTEM = (
    "You are Tradeskeebot, Schyler's market-intelligence analyst. Sober, "
    "data-driven, no hype, no hedging, no disclaimers. You read a fused "
    "sector-rotation sweep (price/RRG + insider flow + news sentiment + "
    "earnings/econ catalysts + policy) and explain what is actually happening."
)

_INSTRUCTIONS = (
    "Below is today's sector-rotation data as JSON. Write an assessment.\n\n"
    "Rules:\n"
    "- Name the specific stocks pulling each sector (use the leaders_up / "
    "leaders_down arrays — symbol, pct, and any news). Say WHO is driving the "
    "move, not just the sector.\n"
    "- Tie moves to the drivers (price, smart_money, media, catalyst, "
    "government) and to news tone when present.\n"
    "- Call out portfolio tailwinds/risks by ticker if relevant.\n"
    "- No filler, no 'as an AI', no investment-advice disclaimer.\n\n"
    "Return ONLY a JSON object, no prose around it, with exactly two keys:\n"
    '  "short": a 3-5 sentence plain-text rotation read (the TL;DR).\n'
    '  "full":  a markdown briefing (a few short sections / bullets) with the '
    "named drivers per sector and the book read.\n\n"
    "DATA:\n"
)


def _build_prompt(payload: Mapping[str, Any]) -> str:
    return (
        _SYSTEM
        + "\n\n"
        + _INSTRUCTIONS
        + json.dumps(payload, default=str, separators=(",", ":"))
    )


def _parse_response(text: Optional[str]) -> Optional[Dict[str, str]]:
    """PURE: pull {short, full} out of the model's text. Tolerant of fences/prose.

    Tries a strict JSON parse first, then a fenced ```json block, then the first
    balanced ``{...}`` object. Falls back to treating the whole text as ``full``
    with a derived ``short``. Returns ``None`` only when there is no usable text.
    """
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()

    candidates: List[str] = []
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    candidates.append(raw)

    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict) and ("short" in obj or "full" in obj):
            short = str(obj.get("short") or "").strip()
            full = str(obj.get("full") or "").strip()
            if not short and full:
                short = _derive_short(full)
            if not full and short:
                full = short
            if short or full:
                return {"short": short, "full": full}

    # No JSON — treat the raw text as the full briefing.
    return {"short": _derive_short(raw), "full": raw}


def _derive_short(full: str) -> str:
    """PURE: a TL;DR fallback — first sentences of the briefing, sans markdown."""
    plain = re.sub(r"[#*`>_\-]+", " ", full)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= 320:
        return plain
    cut = plain[:320]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > 80 else cut).strip() + " …"


async def generate_assessment(
    result: Mapping[str, Any],
    contributors: Optional[Mapping[str, Any]] = None,
    *,
    timeout: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """IO: ask the local Opus worker for the daily rotation assessment.

    Returns ``{"short", "full", "model", "generated_at"}`` or ``None`` if the bus
    is down / the job times out / nothing usable comes back. Never raises — the
    caller treats a ``None`` as "no AI read available" and shows the mechanical
    headline instead.
    """
    try:
        import agent_bridge
    except Exception as e:  # pragma: no cover
        logger.warning("assessment: agent_bridge import failed: %s", e)
        return None

    payload = build_payload(result, contributors)
    if not payload.get("sectors"):
        logger.info("assessment: no scored sectors; skipping AI read")
        return None

    prompt = _build_prompt(payload)
    try:
        text = await agent_bridge.run_agent_job(prompt, kind="data", timeout=timeout)
    except Exception as e:  # noqa: BLE001
        logger.warning("assessment: run_agent_job raised: %s", e)
        return None

    parsed = _parse_response(text)
    if parsed is None:
        return None

    from datetime import datetime, timezone

    return {
        "short": parsed.get("short") or None,
        "full": parsed.get("full") or None,
        "model": "opus-4.8 (agent-bridge)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
