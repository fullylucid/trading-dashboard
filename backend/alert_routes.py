"""Chart-condition smart-alert HTTP surface (thin router over chart_alerts).

- ``GET    /api/alerts``          -> list saved alerts
- ``POST   /api/alerts``          -> create ``{symbol, spec, plot_step, op, value, channel?, note?}``
- ``DELETE /api/alerts/{id}``     -> remove an alert
- ``POST   /api/alerts/check``    -> evaluate all active alerts now, deliver fired ones
  (intended to be hit by a scheduler/timer, like the FinTube scout)
"""
import logging

from fastapi import APIRouter, HTTPException, Path as PathParam, Request

import chart_alerts as _alerts
from indicator_spec import SpecError

logger = logging.getLogger(__name__)

alert_router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@alert_router.get("")
def list_alerts() -> dict:
    return {"alerts": _alerts.list_alerts()}


@alert_router.post("")
async def create_alert(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Body must be JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        return _alerts.save_alert(
            symbol=data.get("symbol", ""),
            spec=data.get("spec"),
            plot_step=data.get("plot_step", ""),
            op=data.get("op", ""),
            value=data.get("value"),
            channel=data.get("channel", "telegram"),
            note=data.get("note", ""),
        )
    except SpecError as e:
        raise HTTPException(status_code=400, detail={"errors": e.errors}) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None


@alert_router.delete("/{alert_id}")
def delete_alert(alert_id: str = PathParam(...)) -> dict:
    return {"deleted": _alerts.delete_alert(alert_id)}


@alert_router.post("/check")
def check_alerts() -> dict:
    """Evaluate all active alerts and deliver any that fired (scheduler entry point)."""
    return _alerts.evaluate_all()
