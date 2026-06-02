"""
Agent Bridge - Cloud <-> Local Claude Code job bus

This module is the cloud-side half of the "messenger -> local Claude" pipeline.
The browser (authenticated by a signed session cookie) enqueues jobs; a worker
running on the user's always-on WSL2 box (authenticated by AGENT_WORKER_TOKEN)
long-polls for jobs, runs `claude -p` locally, and streams results back.

Two non-overlapping credentials:
  - session cookie  -> browser endpoints (login, enqueue, history, approve, conversations)
  - AGENT_WORKER_TOKEN (Bearer) -> worker endpoints (next, result)
The worker token can never enqueue; the session cookie can never poll.

Redis (logical db /1, namespaced `agent:`) is the durable job bus + transcript store.
Mirrors the structure of hermes_portal.py: module-level router + startup/shutdown
events + a set_ws_manager() hook injected by main.py.
"""

import os
import json
import time
import uuid
import asyncio
import secrets
import logging
from datetime import datetime
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, Request, Response, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    aioredis = None
    logger.warning("redis not installed - agent bridge will be unavailable")

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False
    logger.warning("bcrypt not installed - agent login will be unavailable")

try:
    from itsdangerous import URLSafeTimedSerializer
    HAS_ITSDANGEROUS = True
except ImportError:
    HAS_ITSDANGEROUS = False
    logger.warning("itsdangerous not installed - agent sessions will be unavailable")


# ============================================================================
# Configuration
# ============================================================================

# Use a separate logical db so the agent bus never collides with / is evicted
# by the cache that lives in db /0.
# NOTE: some managed Redis tiers expose only db 0. If so, set AGENT_BUS_REDIS_DB=0
# and rely on the `agent:` key namespace + a no-evict maxmemory policy instead.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
AGENT_BUS_REDIS_DB = os.getenv("AGENT_BUS_REDIS_DB", "1")


def _bus_redis_url() -> str:
    """Point the agent bus at its own logical db, preserving every other part of
    the URL. Critically, TLS query params (e.g. ?ssl_cert_reqs=required on a
    managed rediss:// endpoint) MUST survive — the old string-split dropped them."""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(REDIS_URL)
    return urlunsplit(parts._replace(path=f"/{AGENT_BUS_REDIS_DB}"))


OWNER_PASSWORD_HASH = os.getenv("OWNER_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
AGENT_WORKER_TOKEN = os.getenv("AGENT_WORKER_TOKEN", "")

# When true, the app-level password is disabled and Cloudflare Access is the sole
# gate. Safe for a single-user, owner-only-Access deployment with no bypass route
# to the origin. require_session() becomes a no-op and the browser skips login.
AGENT_AUTH_DISABLED = os.getenv("AGENT_AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")

SESSION_COOKIE_NAME = "agent_session"
SESSION_MAX_AGE = 12 * 60 * 60  # 12 hours
SESSION_SALT = "agent-session"
TICKET_SALT = "agent-ws-ticket"
TICKET_MAX_AGE = 60  # WS connect ticket valid 60s

# Rate limit: max enqueues per window per session
RATELIMIT_MAX = 30
RATELIMIT_WINDOW = 60  # seconds

# Idempotency / TTLs
SEEN_TTL = 24 * 60 * 60
JOB_TTL = 7 * 24 * 60 * 60
QUEUE_KEY = "agent:jobs:queue"

# Wall-clock cap for internal (backend-initiated) Claude jobs — theses,
# narratives, explanations. Generous because the work runs off-box on the
# local worker pool; the caller always has a deterministic fallback.
INTERNAL_JOB_TIMEOUT = int(os.getenv("AGENT_INTERNAL_TIMEOUT", "150"))

# ============================================================================
# Module state (wired up by startup_event / set_ws_manager)
# ============================================================================

_redis: Optional["aioredis.Redis"] = None
_redis_block: Optional["aioredis.Redis"] = None  # dedicated client for blocking BLPOP


def _block_redis() -> "aioredis.Redis":
    """Dedicated client for blocking pops: its own connection(s) with NO socket read
    timeout, so a long BLPOP isn't killed mid-block or starved by the shared pool's
    constant traffic. Created lazily on first long-poll."""
    global _redis_block
    if _redis_block is None:
        _redis_block = aioredis.from_url(
            _bus_redis_url(), decode_responses=True,
            socket_timeout=None, socket_keepalive=True,
        )
    return _redis_block
_serializer: Optional["URLSafeTimedSerializer"] = None
_ws_manager = None  # injected by main.py via set_ws_manager()


def set_ws_manager(manager) -> None:
    """Inject the shared WebSocketManager singleton (called from main.py)."""
    global _ws_manager
    _ws_manager = manager
    logger.info("Agent bridge: WebSocket manager wired up")


def _require_ready() -> "aioredis.Redis":
    if _redis is None:
        raise HTTPException(status_code=503, detail="Agent bridge not initialized")
    return _redis


# ============================================================================
# Auth helpers
# ============================================================================

def _get_serializer() -> "URLSafeTimedSerializer":
    if _serializer is None:
        raise HTTPException(status_code=503, detail="Sessions unavailable")
    return _serializer


def issue_session_token() -> str:
    return _get_serializer().dumps({"sub": "owner"}, salt=SESSION_SALT)


def verify_session_token(token: str) -> bool:
    try:
        _get_serializer().loads(token, salt=SESSION_SALT, max_age=SESSION_MAX_AGE)
        return True
    except Exception:
        return False


def issue_ws_ticket() -> str:
    return _get_serializer().dumps({"ws": True}, salt=TICKET_SALT)


def verify_ws_ticket(ticket: str) -> bool:
    try:
        _get_serializer().loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
        return True
    except Exception:
        return False


def require_session(request: Request) -> str:
    """Dependency: validate the signed session cookie. Returns a session id."""
    if AGENT_AUTH_DISABLED:
        # Cloudflare Access is the sole gate; no app-level session required.
        return "owner"
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token or not verify_session_token(token):
        raise HTTPException(status_code=401, detail="Authentication required")
    # session id used for rate-limiting buckets; derive a stable short hash
    return token[-32:]


def require_worker_token(request: Request) -> bool:
    """Dependency: validate the worker Bearer token (constant-time)."""
    auth = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not auth.startswith(prefix) or not AGENT_WORKER_TOKEN:
        raise HTTPException(status_code=401, detail="Worker authentication required")
    presented = auth[len(prefix):]
    if not secrets.compare_digest(presented, AGENT_WORKER_TOKEN):
        raise HTTPException(status_code=401, detail="Worker authentication required")
    return True


# ============================================================================
# Request / response models
# ============================================================================

class LoginRequest(BaseModel):
    password: str


class EnqueueRequest(BaseModel):
    conversation_id: str
    kind: str = "brainstorm"  # code | data | brainstorm | scan
    content: str


class ResultRequest(BaseModel):
    job_id: str
    seq: int
    type: str  # chunk | final | error
    content: str = ""
    conversation_id: Optional[str] = None
    approval_kind: Optional[str] = None
    pr_url: Optional[str] = None
    title: Optional[str] = None
    claude_session_id: Optional[str] = None


class ApproveRequest(BaseModel):
    job_id: str
    action: str  # merge | reject


class NewConversationRequest(BaseModel):
    title: Optional[str] = None


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/agent", tags=["agent"])

VALID_KINDS = {"code", "data", "brainstorm", "scan"}


async def _touch_conversation(r, conversation_id: str) -> None:
    await r.zadd("agent:conv:index", {conversation_id: time.time()})


async def _append_turn(r, conversation_id: str, turn: Dict[str, Any]) -> None:
    await r.rpush(f"agent:conv:{conversation_id}", json.dumps(turn))
    await _touch_conversation(r, conversation_id)


@router.get("/auth-config")
async def auth_config():
    """Unauthenticated: tells the browser whether app-level login is required.
    When False, the messenger skips the password gate (Cloudflare Access only)."""
    return {"auth_required": not AGENT_AUTH_DISABLED}


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    if AGENT_AUTH_DISABLED:
        # App auth is off; treat login as a no-op success.
        return {"status": "ok"}
    if not HAS_BCRYPT or not OWNER_PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Login unavailable")
    try:
        ok = bcrypt.checkpw(req.password.encode("utf-8"), OWNER_PASSWORD_HASH.encode("utf-8"))
    except ValueError:
        ok = False
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = issue_session_token()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"status": "ok"}


@router.post("/logout")
async def logout(request: Request, response: Response):
    require_session(request)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/ws-ticket")
async def ws_ticket(request: Request):
    """Issue a short-lived ticket the browser uses to open /ws/agent."""
    require_session(request)
    return {"ticket": issue_ws_ticket()}


async def _check_rate_limit(r, session_id: str) -> None:
    key = f"agent:ratelimit:{session_id}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, RATELIMIT_WINDOW)
    if count > RATELIMIT_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


@router.post("/enqueue")
async def enqueue(req: EnqueueRequest, request: Request):
    session_id = require_session(request)
    r = _require_ready()
    await _check_rate_limit(r, session_id)

    if req.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind: {req.kind}")

    job_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat() + "Z"

    # Is this the conversation's first turn? (used to request an auto-title)
    existing = await r.llen(f"agent:conv:{req.conversation_id}")
    is_first = existing == 0

    # Prior Claude session id (if any) so the worker can --resume for continuity
    resume_session = await r.hget(f"agent:conv:{req.conversation_id}:meta", "claude_session_id")

    job = {
        "job_id": job_id,
        "kind": req.kind,
        "content": req.content,
        "conversation_id": req.conversation_id,
        "created_at": created_at,
        "needs_title": is_first,
        "resume_session": resume_session,
    }

    await r.hset(f"agent:job:{job_id}", mapping={
        "status": "queued",
        "kind": req.kind,
        "created_at": created_at,
        "conversation_id": req.conversation_id,
    })
    await r.expire(f"agent:job:{job_id}", JOB_TTL)
    await _append_turn(r, req.conversation_id, {
        "role": "user",
        "content": req.content,
        "job_id": job_id,
        "ts": created_at,
    })
    await r.rpush(QUEUE_KEY, json.dumps(job))

    return {"job_id": job_id, "status": "queued"}


@router.get("/next")
async def next_job(request: Request, wait: int = Query(0, ge=0, le=60)):
    # Local Redis supports real BLPOP (the old Upstash bus did not). With wait>0 we
    # block server-side until a job arrives or `wait` seconds elapse, so an idle worker
    # holds ONE open request instead of short-polling every second — near-zero idle
    # wakeups (and the CPU finally stays in deep idle). wait=0 keeps the instant LPOP path.
    require_worker_token(request)
    r = _require_ready()
    # liveness beacon for the System monitor's stack panel (a worker just polled)
    try:
        await r.set("agent:worker:last_poll", time.time())
    except Exception:  # noqa: BLE001 — never let telemetry break the poll
        pass
    if wait > 0:
        rb = _block_redis()  # dedicated no-read-timeout connection for the block
        popped = await rb.blpop(QUEUE_KEY, timeout=wait)  # (key, value) or None on timeout
        raw = popped[1] if popped else None
    else:
        raw = await r.lpop(QUEUE_KEY)
    if raw is None:
        return Response(status_code=204)
    job = json.loads(raw)
    await r.hset(f"agent:job:{job['job_id']}", "status", "running")
    return job


@router.post("/result")
async def post_result(req: ResultRequest, request: Request):
    require_worker_token(request)
    r = _require_ready()
    # liveness beacon (a worker is alive and producing) — for the stack panel
    try:
        await r.set("agent:worker:last_poll", time.time())
    except Exception:  # noqa: BLE001
        pass

    # Idempotency: (job_id, seq) processed at most once.
    seen_key = f"agent:job:{req.job_id}:seen"
    is_new = await r.sadd(seen_key, str(req.seq))
    await r.expire(seen_key, SEEN_TTL)
    if not is_new:
        return {"status": "duplicate"}

    # Resolve conversation_id (worker may omit on chunks)
    conversation_id = req.conversation_id
    if not conversation_id:
        conversation_id = await r.hget(f"agent:job:{req.job_id}", "conversation_id")

    payload = {
        "job_id": req.job_id,
        "seq": req.seq,
        "type": req.type,
        "content": req.content,
        "conversation_id": conversation_id,
        "approval_kind": req.approval_kind,
        "pr_url": req.pr_url,
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    # Persist ordered chunk stream
    await r.rpush(f"agent:result:{req.job_id}", json.dumps(payload))

    # Map conversation -> claude session for --resume continuity
    if req.claude_session_id and conversation_id:
        await r.hset(f"agent:conv:{conversation_id}:meta", "claude_session_id", req.claude_session_id)

    # On final/error, write the assistant turn into the transcript
    if req.type in ("final", "error") and conversation_id:
        await _append_turn(r, conversation_id, {
            "role": "assistant",
            "content": req.content,
            "job_id": req.job_id,
            "type": req.type,
            "approval_kind": req.approval_kind,
            "pr_url": req.pr_url,
            "ts": payload["ts"],
        })
        await r.hset(f"agent:job:{req.job_id}", "status", req.type)

    # Auto-title: store + push a live rename
    if req.title and conversation_id:
        await r.hset(f"agent:conv:{conversation_id}:meta", "title", req.title)
        if _ws_manager is not None:
            await _ws_manager.broadcast_chat(conversation_id, {
                "type": "title_update",
                "conversation_id": conversation_id,
                "title": req.title,
            })

    # Live stream to the browser
    if _ws_manager is not None and conversation_id:
        await _ws_manager.broadcast_chat(conversation_id, payload)

    return {"status": "ok"}


@router.post("/approve")
async def approve(req: ApproveRequest, request: Request):
    require_session(request)
    r = _require_ready()
    if req.action not in ("merge", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action")

    job_meta = await r.hgetall(f"agent:job:{req.job_id}")
    if not job_meta:
        raise HTTPException(status_code=404, detail="Job not found")
    conversation_id = job_meta.get("conversation_id", "")

    control_job_id = str(uuid.uuid4())
    control = {
        "job_id": control_job_id,
        "kind": "approval",
        "action": req.action,
        "target_job_id": req.job_id,
        "conversation_id": conversation_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    await r.hset(f"agent:job:{control_job_id}", mapping={
        "status": "queued",
        "kind": "approval",
        "conversation_id": conversation_id,
    })
    await r.expire(f"agent:job:{control_job_id}", JOB_TTL)
    await r.rpush(QUEUE_KEY, json.dumps(control))
    return {"job_id": control_job_id, "status": "queued"}


@router.get("/history")
async def history(request: Request, conversation_id: str = Query(...)):
    require_session(request)
    r = _require_ready()
    raw = await r.lrange(f"agent:conv:{conversation_id}", 0, -1)
    turns = [json.loads(t) for t in raw]
    meta = await r.hgetall(f"agent:conv:{conversation_id}:meta")
    return {"conversation_id": conversation_id, "turns": turns, "meta": meta}


@router.get("/conversations")
async def list_conversations(request: Request):
    require_session(request)
    r = _require_ready()
    # Most recent first
    ids = await r.zrevrange("agent:conv:index", 0, 99, withscores=True)
    out: List[Dict[str, Any]] = []
    for cid, score in ids:
        meta = await r.hgetall(f"agent:conv:{cid}:meta")
        out.append({
            "conversation_id": cid,
            "title": meta.get("title", "New chat"),
            "last_activity": score,
        })
    return {"conversations": out}


@router.post("/conversations")
async def create_conversation(req: NewConversationRequest, request: Request):
    require_session(request)
    r = _require_ready()
    conversation_id = str(uuid.uuid4())
    await r.hset(f"agent:conv:{conversation_id}:meta", mapping={
        "title": req.title or "New chat",
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    await _touch_conversation(r, conversation_id)
    return {"conversation_id": conversation_id, "title": req.title or "New chat"}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request):
    require_session(request)
    r = _require_ready()
    await r.delete(
        f"agent:conv:{conversation_id}",
        f"agent:conv:{conversation_id}:meta",
    )
    await r.zrem("agent:conv:index", conversation_id)
    return {"status": "ok"}


# ============================================================================
# Internal jobs (backend -> free local Opus, no messenger conversation)
# ============================================================================

async def run_agent_job(
    content: str,
    kind: str = "data",
    timeout: Optional[int] = None,
) -> Optional[str]:
    """Enqueue an internal Claude job and wait for its final text.

    This is how backend features (thesis, narratives, alert/regime
    explanations) reach the free local Opus 4.8 worker pool. Unlike the
    messenger `enqueue` route, internal jobs carry NO conversation_id, so
    they never appear in the chat history and never broadcast over /ws/agent —
    the worker just writes the result to `agent:result:{job_id}`, which we
    poll here.

    Returns the final text on success, or None on error/timeout/bus-down so
    every caller can fall back to deterministic output. Reuses the existing
    read-only worker path (kind="data"); no worker changes required.
    """
    if _redis is None:
        logger.warning("run_agent_job: bus not initialized; returning None")
        return None
    if kind not in VALID_KINDS:
        kind = "data"
    r = _redis
    job_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat() + "Z"
    job = {
        "job_id": job_id,
        "kind": kind,
        "content": content,
        "conversation_id": None,   # internal: no transcript, no broadcast
        "created_at": created_at,
        "needs_title": False,
        "resume_session": None,
    }
    try:
        await r.hset(f"agent:job:{job_id}", mapping={
            "status": "queued", "kind": kind, "created_at": created_at,
        })
        await r.expire(f"agent:job:{job_id}", JOB_TTL)
        await r.rpush(QUEUE_KEY, json.dumps(job))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"run_agent_job: enqueue failed: {e}")
        return None

    deadline = time.time() + (timeout or INTERNAL_JOB_TIMEOUT)
    delay = 1.0
    result: Optional[str] = None
    try:
        while time.time() < deadline:
            await asyncio.sleep(delay)
            delay = min(delay * 1.3, 4.0)
            items = await r.lrange(f"agent:result:{job_id}", 0, -1)
            done = False
            for raw in items:
                try:
                    p = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                if p.get("type") == "final":
                    result = p.get("content") or None
                    done = True
                    break
                if p.get("type") == "error":
                    logger.warning(
                        f"run_agent_job {job_id[:8]} errored: "
                        f"{(p.get('content') or '')[:160]}"
                    )
                    done = True
                    break
            if done:
                break
        else:
            logger.warning(
                f"run_agent_job {job_id[:8]} timed out after "
                f"{timeout or INTERNAL_JOB_TIMEOUT}s"
            )
    finally:
        # Internal jobs are fire-and-forget; don't leave bus keys lingering.
        try:
            await r.delete(f"agent:result:{job_id}", f"agent:job:{job_id}")
        except Exception:  # noqa: BLE001
            pass
    return result


# ============================================================================
# Lifecycle
# ============================================================================

async def startup_event():
    """Connect to Redis (db /1) and the session serializer. Fail loud if the
    bus is unreachable: the worker is a separate machine, so an in-memory
    fallback would silently break the whole pipeline."""
    global _redis, _serializer

    if not (HAS_REDIS and HAS_ITSDANGEROUS):
        raise RuntimeError("agent_bridge requires redis + itsdangerous")
    if not SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET not configured")
    if not AGENT_WORKER_TOKEN:
        raise RuntimeError("AGENT_WORKER_TOKEN not configured")

    _serializer = URLSafeTimedSerializer(SESSION_SECRET)
    _redis = aioredis.from_url(_bus_redis_url(), decode_responses=True)
    await _redis.ping()
    logger.info("Agent bridge: connected to Redis bus (db /1)")


async def shutdown_event():
    global _redis, _redis_block
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    if _redis_block is not None:
        await _redis_block.aclose()
        _redis_block = None
    logger.info("Agent bridge: shutdown complete")
