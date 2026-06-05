"""Chart-condition smart alerts.

An alert is a constrained indicator spec + a condition on one of its plots, evaluated
against a symbol's latest bars. When the condition fires on a NEW bar it's delivered
(Telegram by default, reusing the existing SIGNAL_BOT_* path) — so a single mechanism
covers price-level alerts, indicator crosses, divergence flags, etc., all expressed in
the same no-eval spec grammar the rest of the Charts tab uses.

Storage: Redis hash ``chart:alerts`` (sync client, graceful degradation like
indicator_arsenal). Evaluation reuses ``indicator_spec.interpret`` over bars pulled from
the cached daily OHLC (``scan_analytics._fetch_ohlcv``). Dedup: an alert fires at most
once per new bar (tracked by the latest bar's timestamp).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

import requests

from indicator_spec import SpecError, validate_spec, interpret

logger = logging.getLogger("chart.alerts")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ALERTS_KEY = "chart:alerts"
MAX_ALERTS = 200
OPS = ("gt", "lt", "cross_up", "cross_down")
CHANNELS = ("telegram", "log")

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
            logger.warning("chart alerts redis unavailable: %s", e)
            _client = None
    return _client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# CRUD
# ============================================================================

def list_alerts() -> List[Dict[str, Any]]:
    c = _r()
    if c is None:
        return []
    try:
        raw = c.hgetall(ALERTS_KEY) or {}
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    for v in raw.values():
        try:
            out.append(json.loads(v))
        except (json.JSONDecodeError, TypeError):
            continue
    out.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return out


def get_alert(alert_id: str) -> Optional[Dict[str, Any]]:
    c = _r()
    if c is None:
        return None
    try:
        raw = c.hget(ALERTS_KEY, alert_id)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _put(alert: Dict[str, Any]) -> None:
    c = _r()
    if c is None:
        raise RuntimeError("alert storage unavailable")
    c.hset(ALERTS_KEY, alert["id"], json.dumps(alert))


def save_alert(
    symbol: str,
    spec: Any,
    plot_step: str,
    op: str,
    value: float,
    channel: str = "telegram",
    note: str = "",
) -> Dict[str, Any]:
    """Validate the spec + condition and persist a new alert. Raises on bad input."""
    normalized = validate_spec(spec)  # raises SpecError
    if op not in OPS:
        raise ValueError(f"op must be one of {OPS}")
    if not any(p["step"] == plot_step for p in normalized["plots"]):
        raise ValueError(f"plot_step '{plot_step}' is not a plot of the spec")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("value must be a number") from None
    if channel not in CHANNELS:
        channel = "telegram"
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol required")

    c = _r()
    if c is None:
        raise RuntimeError("alert storage unavailable")
    if c.hlen(ALERTS_KEY) >= MAX_ALERTS:
        raise RuntimeError(f"too many alerts (max {MAX_ALERTS})")

    alert = {
        "id": uuid.uuid4().hex[:10],
        "symbol": sym,
        "spec": normalized,
        "plot_step": plot_step,
        "op": op,
        "value": value,
        "channel": channel,
        "note": str(note)[:200],
        "created_at": _now(),
        "active": True,
        "last_fired_ts": None,
        "last_fired_at": None,
    }
    _put(alert)
    return alert


def delete_alert(alert_id: str) -> bool:
    c = _r()
    if c is None:
        return False
    try:
        return bool(c.hdel(ALERTS_KEY, alert_id))
    except Exception:  # noqa: BLE001
        return False


# ============================================================================
# Evaluation
# ============================================================================

def _bars_for(symbol: str, days: int = 400) -> List[Dict[str, Any]]:
    """Recent daily bars for `symbol` in the interpret() shape. Empty on failure."""
    try:
        import scan_analytics as sa
        df = sa._fetch_ohlcv(symbol, days)
    except Exception as e:  # noqa: BLE001
        logger.info("alert bars fetch failed for %s: %s", symbol, e)
        return []
    if df is None or len(df) == 0:
        return []
    out: List[Dict[str, Any]] = []
    for ts, row in df.iterrows():
        try:
            out.append({
                "timestamp": int(__import__("pandas").Timestamp(ts).timestamp()),
                "open": float(row.get("Open")),
                "high": float(row.get("High")),
                "low": float(row.get("Low")),
                "close": float(row.get("Close")),
                "volume": float(row.get("Volume") or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def _condition_met(op: str, value: float, prev: Optional[float], last: float) -> bool:
    if op == "gt":
        return last > value
    if op == "lt":
        return last < value
    if op == "cross_up":
        return prev is not None and prev <= value < last
    if op == "cross_down":
        return prev is not None and prev >= value > last
    return False


def evaluate(alert: Dict[str, Any], bars: Optional[List[Dict[str, Any]]] = None) -> Tuple[bool, Optional[str]]:
    """Evaluate one alert. Returns (fired_now, message). Mutates alert's last_fired_* on fire.

    `fired_now` is True only on a NEW bar (dedup), so polling repeatedly won't re-fire
    the same bar. Pass `bars` to evaluate against supplied data (tests); otherwise fetched.
    """
    if not alert.get("active", True):
        return False, None
    rows = bars if bars is not None else _bars_for(alert["symbol"])
    if len(rows) < 2:
        return False, None
    try:
        result = interpret(alert["spec"], rows)
    except Exception as e:  # noqa: BLE001
        logger.info("alert interpret failed (%s): %s", alert.get("id"), e)
        return False, None
    plot = next((p for p in result["plots"] if p["step"] == alert["plot_step"]), None)
    if not plot or len(plot["points"]) < 1:
        return False, None
    pts = plot["points"]
    last = pts[-1]["value"]
    prev = pts[-2]["value"] if len(pts) >= 2 else None
    latest_ts = rows[-1]["timestamp"]

    if not _condition_met(alert["op"], alert["value"], prev, last):
        return False, None
    if alert.get("last_fired_ts") == latest_ts:
        return False, None  # already fired on this bar

    alert["last_fired_ts"] = latest_ts
    alert["last_fired_at"] = _now()
    op_txt = {"gt": ">", "lt": "<", "cross_up": "crossed above", "cross_down": "crossed below"}[alert["op"]]
    msg = (
        f"🔔 {alert['symbol']} alert: {alert['spec'].get('short_name', alert['plot_step'])} "
        f"({alert['plot_step']}) {op_txt} {alert['value']} — now {round(float(last), 4)}"
    )
    if alert.get("note"):
        msg += f"\n{alert['note']}"
    return True, msg


def _deliver(channel: str, text: str) -> bool:
    if channel == "log":
        logger.info("alert: %s", text)
        return True
    # Default: Telegram, reusing the existing SIGNAL_BOT_* credentials.
    token = os.getenv("SIGNAL_BOT_TOKEN")
    chat = os.getenv("SIGNAL_BOT_CHAT_ID")
    if not token or not chat:
        logger.warning("SIGNAL_BOT_TOKEN/CHAT_ID not set — alert not delivered")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("alert telegram send failed: %s", e)
        return False


def evaluate_all() -> Dict[str, Any]:
    """Evaluate every active alert; deliver + persist the ones that fired."""
    alerts = list_alerts()
    fired = 0
    checked = 0
    for alert in alerts:
        if not alert.get("active", True):
            continue
        checked += 1
        did, msg = evaluate(alert)
        if did and msg:
            _deliver(alert.get("channel", "telegram"), msg)
            try:
                _put(alert)  # persist last_fired_*
            except Exception:  # noqa: BLE001
                pass
            fired += 1
    return {"checked": checked, "fired": fired, "total": len(alerts)}
