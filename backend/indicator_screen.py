"""Multi-symbol screener — run one constrained indicator spec + condition across a
watchlist and report which symbols match.

Reuses the indicator engine (no eval) and the alert evaluator's bar-fetch + condition
helpers, so a screen is exactly an alert condition applied to N symbols at once. Pure
fan-out over the cached daily OHLC; bounded by MAX_SYMBOLS.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from indicator_spec import validate_spec
from chart_alerts import OPS, _bars_for, _condition_met

logger = logging.getLogger("indicator.screen")
MAX_SYMBOLS = 50


def screen(
    symbols: List[str],
    spec: Any,
    plot_step: str,
    op: str,
    value: float,
    days: int = 400,
) -> List[Dict[str, Any]]:
    """Evaluate `spec`'s `plot_step` against `op value` for each symbol's latest bar.

    Returns ``[{symbol, value, matched, error?}]`` sorted matches-first then by value.
    Raises SpecError (bad spec) / ValueError (bad op/plot_step/value) before fanning out.
    """
    normalized = validate_spec(spec)  # raises SpecError
    if op not in OPS:
        raise ValueError(f"op must be one of {OPS}")
    if not any(p["step"] == plot_step for p in normalized["plots"]):
        raise ValueError(f"plot_step '{plot_step}' is not a plot of the spec")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("value must be a number") from None

    seen: set[str] = set()
    clean: List[str] = []
    for s in symbols or []:
        u = (s or "").strip().upper()
        if u and u not in seen:
            seen.add(u)
            clean.append(u)
    clean = clean[:MAX_SYMBOLS]

    from indicator_spec import interpret

    out: List[Dict[str, Any]] = []
    for sym in clean:
        bars = _bars_for(sym, days)
        if len(bars) < 2:
            out.append({"symbol": sym, "value": None, "matched": False, "error": "no data"})
            continue
        try:
            result = interpret(normalized, bars)
            plot = next((p for p in result["plots"] if p["step"] == plot_step), None)
            pts = plot["points"] if plot else []
            if not pts:
                out.append({"symbol": sym, "value": None, "matched": False, "error": "no values"})
                continue
            last = pts[-1]["value"]
            prev = pts[-2]["value"] if len(pts) >= 2 else None
            out.append({
                "symbol": sym,
                "value": round(float(last), 4),
                "matched": _condition_met(op, value, prev, last),
            })
        except Exception as e:  # noqa: BLE001
            logger.info("screen failed for %s: %s", sym, e)
            out.append({"symbol": sym, "value": None, "matched": False, "error": "compute failed"})

    out.sort(key=lambda r: (r["matched"], r["value"] if r["value"] is not None else float("-inf")), reverse=True)
    return out
