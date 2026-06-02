"""
System monitor API — ingests host hardware/process snapshots from the Windows-side
collector (syswatch.ps1), keeps a short ring buffer per metric in Redis, runs z-score
spike detection with process correlation, and serves the live view + event log to the
🖥️ System dashboard tab.

Data flows HOST -> here (WSL can't reach the host's LHM sensors directly; the collector
pushes). Ingest is token-gated. Everything here is sync (FastAPI threadpool) and cheap;
the only token-spending step is the on-demand "explain" which routes through the agent bus.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

system_router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger("system_routes")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INGEST_TOKEN = os.getenv("SYSTEM_INGEST_TOKEN", "")

# ring/series sizing — ~4s cadence -> 300 pts ≈ 20 min of history
SERIES_MAX = 300
EVENTS_MAX = 200
# metrics we track for spike detection: key -> (absolute floor to even consider, z threshold)
SPIKE_METRICS = {
    "cpu_load":  (35.0, 2.5),   # % — only flag if both abnormal AND meaningfully high
    "gpu_load":  (35.0, 2.5),
    "cpu_temp":  (70.0, 2.5),   # °C
    "gpu_temp":  (70.0, 2.5),
    "cpu_power": (45.0, 2.5),   # W
}
EVENT_COOLDOWN_S = 90  # per-metric debounce so one ramp = one event

_redis_client: Optional["redis.Redis"] = None


def _r() -> Optional["redis.Redis"]:
    global _redis_client
    if redis is None:
        return None
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            _redis_client.ping()
        except Exception as e:  # noqa: BLE001
            logger.warning("system_routes redis unavailable: %s", e)
            _redis_client = None
    return _redis_client


# ---------------------------------------------------------------- ingest model
class Snapshot(BaseModel):
    ts: str                              # ISO8601, host-stamped
    cpu: Dict[str, Any] = {}             # temp, load, power_w, tjmax_distance, warn, crit
    gpu: Dict[str, Any] = {}             # temp, load, fan_rpm, hotspot
    mem: Dict[str, Any] = {}             # used_pct
    disk: Dict[str, Any] = {}            # busy_pct
    fans: List[Dict[str, Any]] = []      # [{name, rpm}]
    top: List[Dict[str, Any]] = []       # [{name,pid,cpu,gpu,net_kbps,signed,path}]
    security: Dict[str, Any] = {}        # {defender:{...}, flags:[...], new_autoruns:[...]}


def _push_series(r, metric: str, value: float) -> List[float]:
    key = f"sys:series:{metric}"
    r.rpush(key, value)
    r.ltrim(key, -SERIES_MAX, -1)
    return [float(x) for x in r.lrange(key, 0, -1)]


def _zscore(series: List[float], value: float) -> float:
    if len(series) < 12:
        return 0.0
    n = len(series)
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    std = var ** 0.5
    if std < 1e-6:
        return 0.0
    return (value - mean) / std


def _severity(metric: str, value: float, z: float, cpu: Dict, gpu: Dict) -> str:
    # temps escalate by LHM's own thresholds; loads/power by z-magnitude
    if metric == "cpu_temp" and value >= float(cpu.get("crit", 999)):
        return "CRITICAL"
    if metric == "cpu_temp" and value >= float(cpu.get("warn", 999)):
        return "WARN"
    if metric == "gpu_temp" and value >= 90:
        return "CRITICAL"
    if abs(z) >= 4:
        return "WARN"
    return "NOTE"


def _detect_spikes(r, snap: Snapshot) -> List[Dict[str, Any]]:
    metric_vals = {
        "cpu_load":  snap.cpu.get("load"),
        "gpu_load":  snap.gpu.get("load"),
        "cpu_temp":  snap.cpu.get("temp"),
        "gpu_temp":  snap.gpu.get("temp"),
        "cpu_power": snap.cpu.get("power_w"),
    }
    now = time.time()
    events: List[Dict[str, Any]] = []
    for metric, (floor, zth) in SPIKE_METRICS.items():
        v = metric_vals.get(metric)
        if v is None:
            continue
        v = float(v)
        series = _push_series(r, metric, v)
        if v < floor:
            continue
        z = _zscore(series[:-1], v)  # z vs the prior distribution, not incl. this point
        if abs(z) < zth:
            continue
        last_key = f"sys:lastevent:{metric}"
        last = r.get(last_key)
        if last and now - float(last) < EVENT_COOLDOWN_S:
            continue
        r.set(last_key, now)
        # correlate: who was hottest on the relevant resource at this instant
        res = "gpu" if metric.startswith("gpu") else "cpu"
        culprit = max(snap.top, key=lambda p: p.get(res, 0), default=None) if snap.top else None
        ev = {
            "ts": snap.ts, "metric": metric, "value": round(v, 1), "z": round(z, 2),
            "severity": _severity(metric, v, z, snap.cpu, snap.gpu),
            "culprit": ({"name": culprit.get("name"), "pid": culprit.get("pid"),
                         "value": culprit.get(res), "signed": culprit.get("signed"),
                         "path": culprit.get("path")} if culprit else None),
            "explained": False, "explanation": None,
        }
        events.append(ev)
    if events:
        for ev in events:
            r.rpush("sys:events", json.dumps(ev))
        r.ltrim("sys:events", -EVENTS_MAX, -1)
    return events


@system_router.post("/ingest")
def ingest(snap: Snapshot, x_system_token: str = Header(default="")) -> Dict[str, Any]:
    if INGEST_TOKEN and x_system_token != INGEST_TOKEN:
        raise HTTPException(401, "bad system token")
    r = _r()
    if r is None:
        raise HTTPException(503, "store unavailable")
    snap_json = snap.model_dump()
    snap_json["_rx"] = time.time()
    r.set("sys:latest", json.dumps(snap_json))
    # security flags are point-in-time; keep the most recent non-empty set visible
    events = _detect_spikes(r, snap)
    return {"ok": True, "events_logged": len(events)}


@system_router.get("/current")
def current() -> Dict[str, Any]:
    r = _r()
    if r is None:
        raise HTTPException(503, "store unavailable")
    raw = r.get("sys:latest")
    if not raw:
        return {"online": False}
    snap = json.loads(raw)
    age = time.time() - snap.get("_rx", 0)
    series = {m: [round(float(x), 1) for x in r.lrange(f"sys:series:{m}", -60, -1)]
              for m in SPIKE_METRICS}
    return {"online": age < 20, "age_s": round(age, 1), "snapshot": snap, "series": series}


@system_router.get("/events")
def events(limit: int = 50) -> Dict[str, Any]:
    r = _r()
    if r is None:
        raise HTTPException(503, "store unavailable")
    raw = r.lrange("sys:events", -limit, -1)
    evs = [json.loads(x) for x in raw]
    evs.reverse()  # newest first
    return {"events": evs}
