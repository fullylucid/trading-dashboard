"""Hydra HQ — cyborganic live-view MJPEG stream (roadmap B2, per STREAM.md).

The WSL half of the on-demand look-dev stream. The Bevy `app` (win-gaia) atomically writes
``stream/live.jpg`` *only while demanded*; this backend:

1. Serves it to the browser as ``multipart/x-mixed-replace`` (MJPEG), tailing ``live.jpg`` and
   substituting an "offline" placeholder when the frame goes stale (>~3s) or is missing.
2. Signals demand on the same shared disk: ``control.json`` ``streaming=true`` while ≥1 viewer
   is connected (bumped every ~30s as a heartbeat), ``false`` after a ~5s grace once the last
   viewer leaves — so the app idles (and the GPU/fan rests) when nobody's watching.

Frames stay on the shared disk; this endpoint is the only thing that emits them, behind the
existing Cloudflare Access SSO. Follows STREAM.md exactly so it interops with the app side.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("hq_stream")

# Container path; bind-mounted from /mnt/c/cyborganic-bus/stream (see docker-compose.box.yml).
# Defaults to the host path so the backend can be run directly on the box for testing.
STREAM_DIR = os.getenv("HQ_STREAM_DIR", "/mnt/c/cyborganic-bus/stream")
LIVE_JPG = os.path.join(STREAM_DIR, "live.jpg")
CONTROL_JSON = os.path.join(STREAM_DIR, "control.json")
OFFLINE_JPG = os.path.join(os.path.dirname(__file__), "assets", "stream_offline.jpg")

# App run/stop control (B3, per CONTROL.md). app-control.json carries a STATE ENUM ONLY (never a
# command) — the Windows launcher is command-locked and ignores everything but `desired`.
APP_CONTROL_JSON = os.path.join(STREAM_DIR, "app-control.json")
APP_STATUS_JSON = os.path.join(STREAM_DIR, "app-status.json")
LIVE_JSON = os.path.join(STREAM_DIR, "live.json")   # {tick, ts, w, h} written by the app
CONTROLLER_STALE_S = 15.0   # app-status.json updated_at older than this -> launcher offline
FPS_WINDOW_S = 8.0          # window over which measured fps is averaged from live.json ticks

# stream params handed to the app via control.json (STREAM.md)
FPS = int(os.getenv("HQ_STREAM_FPS", "12"))
MAX_WIDTH = int(os.getenv("HQ_STREAM_MAX_WIDTH", "960"))
QUALITY = int(os.getenv("HQ_STREAM_QUALITY", "70"))

STALE_S = 3.0          # live.jpg older than this while streaming -> show offline placeholder
GRACE_S = 5.0          # keep the app encoding this long after the last viewer leaves
HEARTBEAT_S = 30.0     # re-stamp control.json updated_at while viewers remain
OFFLINE_FPS = 1.0      # resend the placeholder at most ~1/s
BOUNDARY = "hqframe"


# ---------------------------------------------------------------------------- pure helpers
def control_payload(streaming: bool, now: float) -> dict:
    return {
        "streaming": streaming,
        "fps": FPS,
        "max_width": MAX_WIDTH,
        "quality": QUALITY,
        "updated_at": int(now),
    }


def mjpeg_part(jpeg: bytes, boundary: str = BOUNDARY) -> bytes:
    """Frame one JPEG as a multipart/x-mixed-replace part."""
    return (
        b"--" + boundary.encode() + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
        + jpeg + b"\r\n"
    )


def _load_offline() -> bytes:
    try:
        with open(OFFLINE_JPG, "rb") as f:
            return f.read()
    except OSError:
        return b""


_OFFLINE_BYTES = _load_offline()


# ---------------------------------------------------------------------------- app run/stop (B3)
# the only two desired states HQ may request — anything else is rejected before it reaches disk
_ACTION_TO_DESIRED = {"run": "running", "stop": "stopped"}


def app_control_payload(desired: str, now: float) -> dict:
    """The HQ→launcher control file. STATE ENUM ONLY (CONTROL.md security rule): never a command,
    path, or args. `requested_by` is informational."""
    return {"desired": desired, "requested_at": int(now), "requested_by": "hq"}


def app_status_view(data: Optional[dict], now: float) -> dict:
    """Normalize app-status.json (launcher→HQ) for the UI. `controller_offline` is true when the
    launcher heartbeat (`updated_at`) hasn't advanced in ~15s, or the file is missing/garbage —
    the persistent Windows task isn't running, so Run/Stop are meaningless until it's back."""
    if not isinstance(data, dict):
        return {"controller_offline": True, "state": "offline", "pid": None,
                "since": None, "updated_at": None, "detail": ""}
    updated_at = data.get("updated_at")
    stale = not isinstance(updated_at, (int, float)) or (now - updated_at) > CONTROLLER_STALE_S
    return {
        "controller_offline": bool(stale),
        "state": data.get("state", "unknown"),
        "pid": data.get("pid"),
        "since": data.get("since"),
        "updated_at": updated_at,
        "detail": data.get("detail", ""),
    }


def write_app_control(action: str, now: float) -> dict:
    """Atomically write app-control.json for a validated action. Returns the written payload.
    Raises ValueError for an unknown action (the route turns that into a 400)."""
    desired = _ACTION_TO_DESIRED.get(action)
    if desired is None:
        raise ValueError(f"unknown action: {action!r}")
    payload = app_control_payload(desired, now)
    os.makedirs(STREAM_DIR, exist_ok=True)
    tmp = APP_CONTROL_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, APP_CONTROL_JSON)  # atomic
    return payload


def read_app_status(now: float) -> dict:
    """Read + normalize app-status.json. Never raises — a missing/garbage file reads as offline."""
    try:
        with open(APP_STATUS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    return app_status_view(data, now)


def read_live_meta() -> dict:
    """The app's optional live.json sidecar {tick, ts, w, h} (frame counter + dimensions)."""
    try:
        with open(LIVE_JSON, "r", encoding="utf-8") as f:
            d = json.load(f)
        return {"tick": d.get("tick"), "ts": d.get("ts"), "w": d.get("w"), "h": d.get("h")}
    except (OSError, ValueError):
        return {}


def measure_fps(samples: list) -> Optional[float]:
    """Measured fps = Δtick / Δts across a window of (ts, tick) frame samples. None until there
    are ≥2 samples spanning a meaningful interval — the caller falls back to the target fps."""
    if len(samples) < 2:
        return None
    (ts0, tk0), (ts1, tk1) = samples[0], samples[-1]
    dt, dtick = ts1 - ts0, tk1 - tk0
    if dt <= 0.3 or dtick <= 0:
        return None
    return round(dtick / dt, 1)


_FPS_SAMPLES: list = []


def app_status_full(now: float) -> dict:
    """app-status.json + the live.json sidecar + a measured fps, for the HQ info line (B3).
    Keeps a short rolling window of frame (ts, tick) samples to average the real frame rate."""
    status = read_app_status(now)
    live = read_live_meta()
    ts, tick = live.get("ts"), live.get("tick")
    if isinstance(ts, (int, float)) and isinstance(tick, (int, float)):
        if not _FPS_SAMPLES or _FPS_SAMPLES[-1] != (ts, tick):
            _FPS_SAMPLES.append((ts, tick))
        while len(_FPS_SAMPLES) >= 2 and _FPS_SAMPLES[-1][0] - _FPS_SAMPLES[0][0] > FPS_WINDOW_S:
            _FPS_SAMPLES.pop(0)
    measured = measure_fps(_FPS_SAMPLES)
    status["live"] = live
    status["fps"] = measured if measured is not None else FPS   # fall back to target fps
    status["fps_measured"] = measured is not None
    return status


# ---------------------------------------------------------------------------- demand control
class StreamController:
    """Tracks connected viewers and drives control.json on/off with a grace period."""

    def __init__(self) -> None:
        self.viewers = 0
        self._lock = asyncio.Lock()
        self._hb_task: asyncio.Task | None = None
        self._grace_task: asyncio.Task | None = None

    def _write_control(self, streaming: bool) -> None:
        try:
            os.makedirs(STREAM_DIR, exist_ok=True)
            tmp = CONTROL_JSON + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(control_payload(streaming, time.time()), f)
            os.replace(tmp, CONTROL_JSON)  # atomic
        except OSError as e:  # noqa: BLE001 — never let a disk hiccup kill the stream
            logger.warning("hq_stream control write failed: %s", e)

    async def _heartbeat(self) -> None:
        try:
            while self.viewers > 0:
                self._write_control(True)
                await asyncio.sleep(HEARTBEAT_S)
        except asyncio.CancelledError:
            pass

    async def _grace_then_stop(self) -> None:
        try:
            await asyncio.sleep(GRACE_S)
            if self.viewers == 0:
                self._write_control(False)
                if self._hb_task:
                    self._hb_task.cancel()
                    self._hb_task = None
        except asyncio.CancelledError:
            pass

    async def join(self) -> None:
        async with self._lock:
            self.viewers += 1
            if self._grace_task:  # someone re-joined during the grace window
                self._grace_task.cancel()
                self._grace_task = None
            if self.viewers == 1 and self._hb_task is None:
                self._write_control(True)
                self._hb_task = asyncio.create_task(self._heartbeat())

    async def leave(self) -> None:
        async with self._lock:
            self.viewers = max(0, self.viewers - 1)
            if self.viewers == 0:
                if self._grace_task:
                    self._grace_task.cancel()
                self._grace_task = asyncio.create_task(self._grace_then_stop())


controller = StreamController()


async def mjpeg_generator(request) -> Any:
    """Yield MJPEG parts: the freshest live.jpg, or the offline placeholder when stale/missing.
    Registers/deregisters a viewer so the app only renders while someone's watching."""
    await controller.join()
    last_mtime = 0.0
    last_offline = 0.0
    try:
        # prime the connection immediately so the browser shows something at once
        if _OFFLINE_BYTES:
            yield mjpeg_part(_OFFLINE_BYTES)
        while True:
            if await request.is_disconnected():
                break
            now = time.time()
            served = False
            try:
                mtime = os.path.getmtime(LIVE_JPG)
                if now - mtime <= STALE_S:
                    if mtime != last_mtime:
                        with open(LIVE_JPG, "rb") as f:
                            data = f.read()
                        if data:
                            yield mjpeg_part(data)
                            last_mtime = mtime
                    served = True
            except OSError:
                pass
            if not served and _OFFLINE_BYTES and now - last_offline >= 1.0 / OFFLINE_FPS:
                yield mjpeg_part(_OFFLINE_BYTES)
                last_offline = now
                last_mtime = 0.0
            await asyncio.sleep(1.0 / FPS)
    finally:
        await controller.leave()
