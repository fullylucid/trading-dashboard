"""
Crystal Ball prediction journal — the learn-from-what-works loop.

Every live reversal call can be logged here with a timestamp. Later, once enough
bars have elapsed, the call is RESOLVED against the realized forward return and
scored hit/miss. The accumulated record drives a calibration report: does a
"70% confidence" call actually win ~70% of the time? Without this loop a
predictor is unfalsifiable — which is to say, worthless. With it, the tab earns
(or loses) its credibility out in the open.

Storage is a single JSON file (atomic temp-file + rename on write) under
``CB_JOURNAL_PATH`` (default ``backend/data/crystal_ball_journal.json``). This
module is intentionally PURE: it never fetches prices itself. Resolution takes a
``forward_return_fn(symbol, as_of_iso, horizon) -> float | None`` injected by the
route layer (which uses ``scan_analytics``), so the journal stays trivially
testable and free of network/data coupling.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DEFAULT_PATH = os.path.join(_DEFAULT_DIR, "crystal_ball_journal.json")


def _store_path() -> str:
    return os.environ.get("CB_JOURNAL_PATH", _DEFAULT_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# persistence (atomic)
# ---------------------------------------------------------------------------

def _load() -> List[Dict[str, Any]]:
    path = _store_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: List[Dict[str, Any]]) -> None:
    path = _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, default=str)
        os.replace(tmp, path)  # atomic on POSIX
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def record_prediction(read: Dict[str, Any], *, horizon: int = 10) -> Dict[str, Any]:
    """Append a live Crystal Ball read to the journal as an unresolved prediction.

    Only meaningful directional calls are stored (direction != 'none'); a 'none'
    read is returned unstored so we don't pollute the track record with non-calls.
    """
    direction = read.get("direction", "none")
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": _now_iso(),
        "symbol": read.get("symbol"),
        "direction": direction,
        "reversal_probability": read.get("reversal_probability"),
        "confidence": read.get("confidence"),
        "predictability": read.get("predictability"),
        "last_close": read.get("last_close") if read.get("last_close") is not None
        else (read.get("_debug") or {}).get("last_close"),
        "horizon": horizon,
        "invalidation": read.get("invalidation"),
        "resolved": False,
        "outcome": None,            # 1 = call paid, 0 = it didn't
        "realized_return": None,    # signed forward return over the horizon
        "resolved_ts": None,
    }
    if direction == "none":
        entry["stored"] = False
        return entry
    entries = _load()
    entries.append(entry)
    _save(entries)
    entry["stored"] = True
    return entry


def list_predictions(symbol: Optional[str] = None, limit: int = 100,
                     include_resolved: bool = True) -> List[Dict[str, Any]]:
    entries = _load()
    if symbol:
        s = symbol.upper()
        entries = [e for e in entries if (e.get("symbol") or "").upper() == s]
    if not include_resolved:
        entries = [e for e in entries if not e.get("resolved")]
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return entries[:limit]


def resolve_predictions(
    forward_return_fn: Callable[[str, str, int], Optional[float]],
    *,
    min_age_days: float = 1.0,
) -> Dict[str, Any]:
    """Resolve every unresolved, sufficiently-aged prediction.

    ``forward_return_fn(symbol, as_of_iso, horizon)`` returns the signed close-to-
    close return over ``horizon`` bars starting at/after ``as_of_iso``, or ``None``
    if the horizon hasn't fully elapsed / data is missing. A call is a HIT when the
    forward return agrees with the predicted reversal direction:
        bottom (bullish) -> forward_return > 0
        top    (bearish) -> forward_return < 0
    """
    entries = _load()
    resolved = 0
    skipped = 0
    changed = False
    now = datetime.now(timezone.utc)
    for e in entries:
        if e.get("resolved"):
            continue
        # Age gate (cheap pre-filter; the real gate is whether the horizon elapsed).
        try:
            age_days = (now - datetime.fromisoformat(e["ts"])).total_seconds() / 86400.0
        except Exception:  # noqa: BLE001
            age_days = min_age_days
        if age_days < min_age_days:
            skipped += 1
            continue
        sym = e.get("symbol")
        if not sym:
            continue
        try:
            fwd = forward_return_fn(sym, e["ts"], int(e.get("horizon", 10)))
        except Exception:  # noqa: BLE001
            fwd = None
        if fwd is None:
            skipped += 1
            continue
        hit = 1 if ((e["direction"] == "bottom" and fwd > 0) or
                    (e["direction"] == "top" and fwd < 0)) else 0
        e["resolved"] = True
        e["outcome"] = hit
        e["realized_return"] = round(float(fwd), 5)
        e["resolved_ts"] = _now_iso()
        resolved += 1
        changed = True
    if changed:
        _save(entries)
    return {"resolved": resolved, "skipped": skipped, "total": len(entries)}


def calibration_report() -> Dict[str, Any]:
    """Score the resolved track record: hit-rate + Brier, sliced by confidence
    and by probability bucket. This is the honest report card for the tab."""
    entries = [e for e in _load() if e.get("resolved") and e.get("outcome") is not None]
    n = len(entries)
    base = {"n_resolved": n, "n_open": sum(1 for e in _load() if not e.get("resolved"))}
    if n == 0:
        return {**base, "hit_rate": None, "brier": None, "by_confidence": [], "by_probability": [],
                "note": "No resolved predictions yet — run resolve after the horizon elapses."}

    import numpy as np
    probs = np.array([float(e.get("reversal_probability") or 0.0) for e in entries])
    outs = np.array([float(e["outcome"]) for e in entries])
    hit_rate = float(np.mean(outs))
    brier = float(np.mean((probs - outs) ** 2))

    by_conf = []
    for lvl in ("high", "medium", "low"):
        m = np.array([e.get("confidence") == lvl for e in entries])
        if m.any():
            by_conf.append({"confidence": lvl, "n": int(m.sum()),
                            "hit_rate": round(float(np.mean(outs[m])), 3),
                            "avg_prob": round(float(np.mean(probs[m])), 3)})

    by_prob = []
    lo = 0.5
    for hi in (0.6, 0.7, 0.8, 0.9, 1.01):
        m = (probs >= lo) & (probs < hi)
        if m.any():
            by_prob.append({"range": f"{lo:.2f}-{min(hi,1.0):.2f}", "n": int(m.sum()),
                            "predicted": round(float(np.mean(probs[m])), 3),
                            "realized": round(float(np.mean(outs[m])), 3)})
        lo = hi

    return {**base, "hit_rate": round(hit_rate, 3), "brier": round(brier, 4),
            "by_confidence": by_conf, "by_probability": by_prob,
            "interpretation": _interpret(hit_rate, brier)}


def _interpret(hit_rate: float, brier: float) -> str:
    bits = []
    if brier < 0.20:
        bits.append("well-calibrated")
    elif brier < 0.25:
        bits.append("roughly calibrated")
    else:
        bits.append("poorly calibrated (worse than a coin flip on Brier)")
    if hit_rate >= 0.55:
        bits.append(f"directional edge present ({hit_rate*100:.0f}% hits)")
    elif hit_rate >= 0.45:
        bits.append(f"no clear directional edge ({hit_rate*100:.0f}% hits)")
    else:
        bits.append(f"NEGATIVE edge ({hit_rate*100:.0f}% hits) — fade or fix the model")
    return "; ".join(bits)
