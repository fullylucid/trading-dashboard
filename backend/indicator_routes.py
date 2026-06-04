"""Indicator-spec engine HTTP surface.

Thin router over :mod:`indicator_spec`. Three endpoints, all open like the rest of
the dashboard data routes (edge auth protects the human path):

- ``GET  /api/indicator/ops``      -> the op catalog (whitelist + limits), for the
  AI prompt / a future spec editor.
- ``POST /api/indicator/validate`` -> ``{spec}`` -> ``{valid, errors?, normalized?}``.
- ``POST /api/indicator/compute``  -> ``{spec, bars}`` -> render-ready plots.

The compute endpoint is a pure function of its body — the caller passes the exact
bars to compute over (typically the bars the chart is already showing), so the
series align and nothing is fetched server-side. No ``eval``: the spec is data,
interpreted by a deterministic NumPy evaluator (see indicator_spec).
"""
import logging

from fastapi import APIRouter, HTTPException, Request

import indicator_spec as _engine
from indicator_spec import SpecError

logger = logging.getLogger(__name__)

indicator_router = APIRouter(prefix="/api/indicator", tags=["indicator"])


@indicator_router.get("/ops")
def ops() -> dict:
    """The op whitelist + limits, so a spec author (AI or UI) knows the grammar."""
    return {
        "ops": {
            "source": sorted(_engine.SOURCE_OPS),
            "window": sorted(_engine.WINDOW_OPS),
            "binary": sorted(_engine.BINARY_OPS),
            "unary": sorted(_engine.UNARY_OPS),
            "clamp": sorted(_engine.CLAMP_OP),
        },
        "series": list(_engine.OHLCV_SERIES),
        "panes": list(_engine.PANES),
        "plot_types": list(_engine.PLOT_TYPES),
        "default_periods": _engine._DEFAULT_PERIOD,
        "limits": {
            "max_steps": _engine.MAX_STEPS,
            "max_plots": _engine.MAX_PLOTS,
            "max_period": _engine.MAX_PERIOD,
            "max_bars": _engine.MAX_BARS,
            "max_name_len": _engine.MAX_NAME_LEN,
        },
    }


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Body must be JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    return data


@indicator_router.post("/validate")
async def validate(request: Request) -> dict:
    """Validate a spec without computing. Always 200; ``valid`` carries the verdict."""
    data = await _body(request)
    try:
        normalized = _engine.validate_spec(data.get("spec"))
    except SpecError as e:
        return {"valid": False, "errors": e.errors}
    return {"valid": True, "normalized": normalized}


@indicator_router.post("/compute")
async def compute(request: Request) -> dict:
    """Validate + evaluate a spec over the supplied bars; return render-ready plots."""
    data = await _body(request)
    try:
        normalized = _engine.validate_spec(data.get("spec"))
    except SpecError as e:
        raise HTTPException(status_code=400, detail={"errors": e.errors}) from None

    bars = data.get("bars")
    try:
        result = _engine.interpret(normalized, bars)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:  # noqa: BLE001
        logger.warning("indicator compute failed: %s", e)
        raise HTTPException(status_code=500, detail="Indicator compute failed") from None
    return result
