"""Hydra HQ API — fleet command center (DESIGN.md §7).

Thin, read-only passthrough of the ``hq:fleet`` snapshot that the host-side collector
(scripts/hq_collector.py) pushes to Redis every ~10s. The backend runs in Docker and can't
see host paths/tmux/git/gh, so ALL aggregation happens on the host; this router just serves
the pre-built, already-redacted snapshot to the /hq route.

Same ``_r()``/APIRouter pattern as system_routes.py. Everything here is sync, cheap, and
~0 tokens. Lives behind the existing Cloudflare Access SSO with the rest of the dashboard.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore

hq_router = APIRouter(prefix="/api/hq", tags=["hq"])
logger = logging.getLogger("hq_routes")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FLEET_KEY = "hq:fleet"
ROOMS_KEY = "hq:rooms"
MEMORY_KEY = "hq:memory"
HEADS_KEY = "hq:heads"
COMMANDS_KEY = "hq:commands"
ROADMAP_KEY = "hq:roadmap"
AUTOPILOT_PREFIX = "hq:autopilot:"   # per-room milestone-autopilot intent the engine consumes

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
            logger.warning("hq_routes redis unavailable: %s", e)
            _redis_client = None
    return _redis_client


def _get_json(r, key: str) -> Optional[Any]:
    raw = r.get(key) if r is not None else None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


@hq_router.get("/fleet")
def fleet() -> Dict[str, Any]:
    """The whole-fleet snapshot: rooms, heads (status/current/branch/git), activity, memory.

    Read-only passthrough of Redis ``hq:fleet`` (built host-side by hq_collector.py). Returns
    ``{"available": false}`` if the collector hasn't run yet / the key expired, so the UI can
    show a clean "collector offline" state instead of erroring.
    """
    data = _get_json(_r(), FLEET_KEY)
    if data is None:
        return {"available": False}
    data["available"] = True
    return data


@hq_router.get("/room/{room_id}")
def room(room_id: str) -> Dict[str, Any]:
    """One project room: its heads + open PRs (from the fleet snapshot) merged with its
    rendered key docs (README/blueprint/roadmap/architecture, from ``hq:rooms``).

    404 if the room isn't in the current snapshot; ``{"available": false}`` if the collector
    hasn't run at all. Docs are already secret-scrubbed + size-capped host-side.
    """
    r = _r()
    fleet_data = _get_json(r, FLEET_KEY)
    if fleet_data is None:
        return {"available": False}

    match = next((rm for rm in fleet_data.get("rooms", []) if rm.get("id") == room_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"unknown room: {room_id}")

    rooms_detail = _get_json(r, ROOMS_KEY) or {}
    docs = (rooms_detail.get("rooms", {}).get(room_id, {}) or {}).get("docs", [])

    heads = [h for h in fleet_data.get("heads", []) if h.get("room") == room_id]
    return {
        "available": True,
        "generated_at": fleet_data.get("generated_at"),
        "room": {**match, "docs": docs},
        "heads": heads,
    }


@hq_router.get("/head/{name}")
def head(name: str) -> Dict[str, Any]:
    """One head's detail: its fleet card (status/current/git/branch/rc) merged with its recent
    commits, fossil-archive index, and memory scope (from ``hq:heads``), plus the open PRs it
    owns. 404 if the head isn't in the current snapshot.

    Fossils ship as a metadata index only (names/sizes/mtimes) — never bodies (DESIGN §8).
    """
    r = _r()
    fleet_data = _get_json(r, FLEET_KEY)
    if fleet_data is None:
        return {"available": False}

    card = next((h for h in fleet_data.get("heads", []) if h.get("name") == name), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"unknown head: {name}")

    detail = (_get_json(r, HEADS_KEY) or {}).get("heads", {}).get(name, {})
    open_prs = [
        pr for rm in fleet_data.get("rooms", []) for pr in rm.get("open_prs", [])
        if pr.get("head") == name
    ]
    return {
        "available": True,
        "generated_at": fleet_data.get("generated_at"),
        "head": {
            **card,
            "recent_commits": detail.get("recent_commits", []),
            "fossils": detail.get("fossils", {"count": 0, "files": []}),
            "memory_scope": detail.get("memory_scope", []),
            "open_prs": open_prs,
        },
    }


@hq_router.post("/room/{room_id}/app")
async def room_app_control(room_id: str, request: Request) -> Dict[str, Any]:
    """Run/stop the room's app from HQ (B3, per CONTROL.md). Body: ``{"action": "run"|"stop"}``.
    Writes a STATE ENUM (never a command) to app-control.json; the command-locked Windows
    launcher reconciles actual→desired. Behind Access SSO (owner-only)."""
    if room_id != "cyborganic":
        raise HTTPException(status_code=404, detail=f"no app control for room: {room_id}")
    import time

    import hq_stream
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    action = (body or {}).get("action")
    try:
        payload = hq_stream.write_app_control(action, time.time())
    except ValueError:
        raise HTTPException(status_code=400, detail="action must be 'run' or 'stop'")
    return {"ok": True, "control": payload}


@hq_router.get("/room/{room_id}/app")
def room_app_status(room_id: str) -> Dict[str, Any]:
    """The app's actual state for HQ (B3). Reads app-status.json (written by the launcher);
    reports ``controller_offline`` when its heartbeat is stale / the launcher isn't running."""
    if room_id != "cyborganic":
        raise HTTPException(status_code=404, detail=f"no app control for room: {room_id}")
    import time

    import hq_stream
    return {"available": True, **hq_stream.app_status_full(time.time())}


@hq_router.get("/room/{room_id}/stream")
async def room_stream(room_id: str, request: Request) -> StreamingResponse:
    """Live MJPEG view of a room's app (B2, per STREAM.md). On-demand: connecting drives the
    viewer count up (the collector-independent stream controller writes control.json so the
    app starts rendering); disconnecting releases it. Only cyborganic has a stream wired today.

    Frames stay on the shared disk; this Access-gated endpoint is their only exit.
    """
    if room_id != "cyborganic":
        raise HTTPException(status_code=404, detail=f"no live stream for room: {room_id}")
    import hq_stream

    return StreamingResponse(
        hq_stream.mjpeg_generator(request),
        media_type=f"multipart/x-mixed-replace; boundary={hq_stream.BOUNDARY}",
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )


def _head_workdir(name: str) -> Optional[str]:
    """Resolve a head name -> its workdir from the fleet snapshot (the collector records it)."""
    return (_head_card(name) or {}).get("workdir")


def _head_card(name: str) -> Optional[Dict[str, Any]]:
    fleet = _get_json(_r(), FLEET_KEY)
    if fleet is None:
        return None
    return next((x for x in fleet.get("heads", []) if x.get("name") == name), None)


@hq_router.get("/head/{name}/transcript")
def head_transcript(
    name: str, limit: int = 60, after: Optional[int] = None, file: Optional[str] = None
) -> Dict[str, Any]:
    """The head's live conversation (CONSOLE.md Slice 1, read-only). Resolves name -> workdir ->
    newest Claude transcript .jsonl and returns parsed chat turns. Live-tail: pass ``after``
    (the prior ``cursor`` byte offset) + ``file`` (the prior ``file``) to fetch only new turns;
    on file rotation (newest != ``file``) the server returns a fresh page. Behind Access SSO."""
    import hq_console

    card = _head_card(name)
    workdir = (card or {}).get("workdir")
    status = (card or {}).get("status")   # working/idle/waiting-input -> the console derives "queued"
    if not workdir:
        # unknown head, or an external/bus head with no local transcript
        return {"available": False, "reason": "no transcript for this head"}

    path = hq_console.newest_transcript(workdir)
    if not path:
        return {"available": True, "status": status, "file": None, "cursor": 0, "turns": []}

    current = os.path.basename(path)
    # incremental tail only if the client is still on the current file; else send a fresh page
    same_file = file is not None and file == current
    use_after = after if (same_file and after is not None and after >= 0) else None
    turns, cursor = hq_console.read_turns(path, limit=limit, after=use_after)
    return {"available": True, "status": status, "file": current,
            "rotated": file is not None and not same_file, "cursor": cursor, "turns": turns}


def _head_pane(name: str) -> Optional[str]:
    """Resolve a head name -> its tmux pane id from the fleet snapshot (collector-built)."""
    fleet = _get_json(_r(), FLEET_KEY)
    if fleet is None:
        return None
    h = next((x for x in fleet.get("heads", []) if x.get("name") == name), None)
    tmux = (h or {}).get("tmux") or {}
    return tmux.get("pane")


@hq_router.post("/head/{name}/input")
async def head_input(name: str, request: Request) -> Dict[str, Any]:
    """Send text to a head's tmux pane (CONSOLE.md Slice 2). Body: ``{"text": "..."}``.

    ⚠️ THE most sensitive endpoint in HQ — sending input to a pane is remote control of the box.
    It's gated by Cloudflare Access SSO (owner-only) on a localhost-bound backend; there is no
    public route. The backend (in Docker, no tmux) does NOT execute anything — it validates,
    AUDITS, and enqueues a job to Redis. A host-side relay runs the actual `tmux send-keys`.
    Every send is recorded (who/when/head/pane/text) to the audit log + the app log.
    """
    import time
    import uuid

    import hq_console

    pane = _head_pane(name)
    if not hq_console.valid_pane(pane):
        raise HTTPException(status_code=409, detail=f"head '{name}' is not drivable (no tmux pane)")

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    # text + optional pre-uploaded attachments (folded in as [image/file attached] path lines)
    attachments = (body or {}).get("attachments") or []
    try:
        if attachments:
            text = hq_console.build_message((body or {}).get("text") or "", attachments)
        else:
            text = hq_console.clean_input_text((body or {}).get("text"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    by = request.headers.get("Cf-Access-Authenticated-User-Email") or "local"
    jid = uuid.uuid4().hex[:12]
    job = hq_console.input_job(name, pane, text, by, time.time(), jid)

    r = _r()
    if r is None:
        raise HTTPException(status_code=503, detail="queue unavailable")
    # audit BEFORE enqueue, so nothing is sent without a record
    audit = {"id": jid, "ts": job["ts"], "by": by, "head": name, "pane": pane, "text": text}
    try:
        r.rpush(hq_console.INPUT_AUDIT, json.dumps(audit))
        r.ltrim(hq_console.INPUT_AUDIT, -hq_console.INPUT_AUDIT_MAX, -1)
    except Exception:  # noqa: BLE001
        pass
    logger.info("hq console input by=%s head=%s pane=%s len=%d id=%s", by, name, pane, len(text), jid)
    r.rpush(hq_console.INPUT_QUEUE, json.dumps(job))
    return {"ok": True, "id": jid, "head": name, "pane": pane, "text": text}


@hq_router.post("/head/{name}/upload")
async def head_upload(name: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Save a photo/document to the shared uploads dir — SAVE ONLY, no delivery (attach-then-send).
    The file sits as a pending attachment in the composer; delivery happens on /input, which folds
    the returned `host_path` into the message. Returns {name, host_path, image, size}. Access SSO."""
    import os as _os
    import uuid

    import hq_console

    if not _head_pane(name):
        raise HTTPException(status_code=409, detail=f"head '{name}' is not drivable (no tmux pane)")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > hq_console.UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file too large")

    fid = uuid.uuid4().hex[:12]
    fname = hq_console.safe_upload_name(file.filename or "file", fid)
    try:
        _os.makedirs(hq_console.UPLOADS_DIR, exist_ok=True)
        with open(_os.path.join(hq_console.UPLOADS_DIR, fname), "wb") as f:
            f.write(data)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not save upload: {e}")

    logger.info("hq console upload-saved head=%s file=%s bytes=%d", name, fname, len(data))
    return {"ok": True, "name": fname, "host_path": _os.path.join(hq_console.UPLOADS_DIR_HOST, fname),
            "image": hq_console.is_image(fname), "size": len(data)}


@hq_router.get("/uploads/{name}")
def serve_upload(name: str):
    """Serve a saved upload by name for the chat thumbnail/lightbox — from the uploads dir ONLY,
    path-safe (basename, no traversal). Behind Access SSO; private short cache."""
    import os as _os

    import hq_console
    from fastapi.responses import FileResponse

    safe = _os.path.basename(name)
    if not safe or safe != name or safe.startswith("."):
        raise HTTPException(status_code=400, detail="bad name")
    path = _os.path.join(hq_console.UPLOADS_DIR, safe)
    real = _os.path.realpath(path)
    if not real.startswith(_os.path.realpath(hq_console.UPLOADS_DIR) + _os.sep) or not _os.path.isfile(real):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(real, headers={"Cache-Control": "private, max-age=3600"})


@hq_router.get("/input/{jid}/status")
def input_status(jid: str) -> Dict[str, Any]:
    """Delivery status of a sent message/upload (F4 + instant-echo). The host relay writes a
    per-job result (``hq:input:result:<id>``) right after send-keys; until then it's pending."""
    raw = (_r().get(f"hq:input:result:{jid}") if _r() is not None else None)
    if not raw:
        return {"status": "pending"}
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"status": "pending"}
    return {"status": "delivered" if d.get("ok") else "failed", "ts": d.get("ts")}


@hq_router.get("/room/{room_id}/roadmap")
def room_roadmap(room_id: str) -> Dict[str, Any]:
    """The room's living roadmap (CONSOLE roadmap card): the nested checklist fused with PR state,
    plus the currently-set autopilot milestone. Read-only passthrough of ``hq:roadmap``."""
    r = _r()
    data = _get_json(r, ROADMAP_KEY)
    if data is None:
        return {"available": False}
    rm = (data.get("rooms") or {}).get(room_id)
    if rm is None:
        return {"available": True, "roadmap": None}   # no roadmap file in this room yet
    ap = _get_json(r, AUTOPILOT_PREFIX + room_id) or {}
    return {"available": True, "generated_at": data.get("generated_at"),
            "roadmap": {**rm, "active_milestone": ap.get("milestone")}}


@hq_router.post("/room/{room_id}/autopilot")
async def room_autopilot(room_id: str, request: Request) -> Dict[str, Any]:
    """Set / clear the milestone-bounded autopilot target for a room (the autopilot cockpit).
    Body: ``{"milestone": "R12"}`` to arm, ``{"milestone": null}`` to disarm. This only writes an
    INTENT to Redis (``hq:autopilot:<room>``) that the orchestration engine reads — HQ never runs
    the loop. Audited; behind Access SSO (owner-only)."""
    import time

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    milestone = (body or {}).get("milestone")
    r = _r()
    if r is None:
        raise HTTPException(status_code=503, detail="queue unavailable")
    by = request.headers.get("Cf-Access-Authenticated-User-Email") or "local"
    key = AUTOPILOT_PREFIX + room_id
    if milestone:
        intent = {"room": room_id, "milestone": str(milestone)[:120], "requested_at": int(time.time()), "requested_by": by}
        try:
            r.set(key, json.dumps(intent))
            r.rpush("hq:autopilot:audit", json.dumps(intent))
            r.ltrim("hq:autopilot:audit", -200, -1)
        except Exception:  # noqa: BLE001
            pass
        logger.info("hq autopilot armed by=%s room=%s milestone=%s", by, room_id, intent["milestone"])
        return {"ok": True, "active_milestone": intent["milestone"]}
    try:
        r.delete(key)
    except Exception:  # noqa: BLE001
        pass
    logger.info("hq autopilot disarmed by=%s room=%s", by, room_id)
    return {"ok": True, "active_milestone": None}


@hq_router.get("/commands")
def commands() -> Dict[str, Any]:
    """Slash-command catalog for the console composer autocomplete (built-ins + skills + custom).
    Read-only passthrough of ``hq:commands`` (enumerated host-side by the collector)."""
    data = _get_json(_r(), COMMANDS_KEY)
    if data is None:
        return {"available": False, "commands": []}
    data["available"] = True
    return data


@hq_router.get("/input/audit")
def input_audit(limit: int = 50) -> Dict[str, Any]:
    """Recent console inputs (who/when/head/text) — read-only transparency for the operator."""
    import hq_console

    r = _r()
    if r is None:
        return {"available": False, "entries": []}
    try:
        raw = r.lrange(hq_console.INPUT_AUDIT, -max(1, min(limit, 500)), -1)
    except Exception:  # noqa: BLE001
        return {"available": False, "entries": []}
    entries = []
    for x in raw:
        try:
            entries.append(json.loads(x))
        except ValueError:
            continue
    entries.reverse()  # newest first
    return {"available": True, "entries": entries}


@hq_router.get("/memory")
def memory_index() -> Dict[str, Any]:
    """The memory knowledge-base index: one lightweight entry per ``memory/*.md`` (name, title,
    description, type, scope, link count). Bodies are fetched per-doc via /memory/{name}.

    Read-only passthrough of ``hq:memory`` (built + secret-scrubbed host-side from the
    git-tracked memory dir). ``{"available": false}`` if the collector hasn't run.
    """
    data = _get_json(_r(), MEMORY_KEY)
    if data is None:
        return {"available": False}
    return {
        "available": True,
        "generated_at": data.get("generated_at"),
        "index": data.get("index", []),
    }


@hq_router.get("/memory/{name}")
def memory_doc(name: str) -> Dict[str, Any]:
    """One memory doc: its frontmatter + scrubbed body + outbound/inbound ``[[wikilinks]]``.

    ``links_out`` is annotated with whether each target exists (so the UI can style broken
    links). 404 if the name isn't in the knowledge base.
    """
    data = _get_json(_r(), MEMORY_KEY)
    if data is None:
        return {"available": False}
    docs = data.get("docs", {})
    doc = docs.get(name)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"unknown memory: {name}")
    links_out = [{"name": l, "exists": l in docs} for l in doc.get("links_out", [])]
    return {"available": True, "generated_at": data.get("generated_at"), "doc": {**doc, "links_out": links_out}}
