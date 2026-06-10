#!/usr/bin/env python3
"""Hydra HQ orchestrator — the 0-token idle/handoff detector (ORCHESTRATION.md, build step 1+3).

The self-driving-project loop's deterministic half. This script runs on the HOST (sibling of
hq_collector.py, same single-cycle/supervising-loop + docker-exec-redis patterns) and:

1. Watches each head's WORKING -> IDLE transition off the collector's ``hq:fleet`` snapshot
   (the collector already derives status; we just diff against the last cycle's statuses).
2. When a WORKER head in an AUTOPILOT-ARMED room finishes, reads its HANDOFF — the last
   assistant turn of its live transcript (secret-scrubbed + capped) plus PR/commit cues from
   the fleet snapshot.
3. NOTIFIES the room's LEAD head (cyborganic -> sim-gaia) with the handoff and a "review and
   dispatch its next task" instruction — via the SAME bounded input path the console uses: an
   ``hq_console.input_job``-shaped job RPUSHed to ``hq:input:queue``; the relay send-keys it.
   The lead does ALL the reasoning (review / merge / queue / next prompt). This script never
   thinks, so the loop costs tokens only when a worker actually finishes.

Guardrails (every one required by ORCHESTRATION.md — autonomy is in *tasking*, not shipping):
- ARMED-ONLY:   acts only on rooms with an ``hq:autopilot:<room>`` intent (the console writes
                it; re-arming resets the budget + clears a pause).
- STOP flag:    ``hq:orchestrator:stop`` (global) or ``hq:orchestrator:stop:<room>`` halts the
                loop immediately.
- BUDGET CAP:   after N dispatches per arming (default 8), the room PAUSES + is flagged in
                ``hq:orchestrator:status`` for HQ to surface — never unbounded.
- LOOP-GUARD:   the last-handled (head, task-signature) is remembered; the same finished task
                is never re-notified (a worker ping-ponging working/idle on one task fires once).
- MILESTONE:    when the room's roadmap reaches the armed milestone (every checklist item
                before the ``{milestone:NAME}`` marker done), the loop halts + escalates
                instead of dispatching past the line Schyler drew.

DRY-RUN IS THE DEFAULT. Every detection and the exact notify it WOULD enqueue are logged +
audited, but nothing touches ``hq:input:queue`` until ``--drive`` (or HQ_ORCH_DRIVE=1) is
explicitly given — so the whole loop can be reviewed live before it ever drives a head.

Install:  cp scripts/hq_orchestrator.py ~/.local/bin/hq-orchestrator.py
Run:      while :; do python3 ~/.local/bin/hq-orchestrator.py; sleep 10; done   (one cycle/exec)

Security: same posture as the collector — only DERIVED, REDACTED text leaves the host. The
handoff is model prose, but it's secret-scrubbed anyway (defense-in-depth), and it travels the
already-audited console input path (relay validates the pane against the live hydra session).
The pure helpers below are unit-tested in backend/tests/test_hq_orchestrator.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
REDIS_CONTAINER = os.getenv("HQ_REDIS_CONTAINER", "tdbox-redis")

FLEET_KEY = "hq:fleet"                      # collector's snapshot (statuses, panes, git, PRs)
ROADMAP_KEY = "hq:roadmap"                  # collector's per-room roadmap (milestone check)
AUTOPILOT_PREFIX = "hq:autopilot:"          # per-room arming intent (hq_routes writes it)
STOP_KEY = "hq:orchestrator:stop"           # global kill switch (any value = stop)
STOP_PREFIX = "hq:orchestrator:stop:"       # per-room kill switch
STATE_KEY = "hq:orchestrator:state"         # cross-cycle memory (statuses, loop-guard, budget)
STATUS_KEY = "hq:orchestrator:status"       # what HQ surfaces (mode, per-room counters, pauses)
AUDIT_KEY = "hq:orchestrator:audit"         # capped list of every decision this script makes
INPUT_QUEUE = "hq:input:queue"              # the console's bounded input path (relay consumes)
AUDIT_MAX = 500
STATUS_TTL_S = 600

DISPATCH_CAP = int(os.getenv("HQ_ORCH_CAP", "8"))   # dispatches per arming before auto-pause
HANDOFF_MAX_CHARS = 1500                            # transcript-tail slice shipped to the lead
NOTIFY_MAX_CHARS = 6000                             # full message cap (< console INPUT_TEXT_MAX)
SENDER = "hq-orchestrator"

# Per-room lead heads (ORCHESTRATION.md "Per-project leads"). Overridable via the HQ org-chart
# file (rooms.config.json: {"orchestration": {"leads": {...}, "cap": N}}) so new rooms onboard
# by config, not code. Pilot scope: cyborganic only; solo rooms have no lead = never dispatched.
ROOMS_CONFIG_PATH = os.getenv("HQ_ROOMS_CONFIG", os.path.join(HOME, "hydra-hq", "rooms.config.json"))
DEFAULT_LEADS = {"cyborganic": "sim-gaia"}

# token/secret shapes scrubbed from any text before it leaves the host (same as hq_collector)
_SECRET_PATTERNS = [
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    re.compile(r"(?i)\b(token|secret|api[-_]?key|password|passwd|bearer)\b\s*[=:]\s*\S+"),
]


# ---------------------------------------------------------------------------- #
# Pure helpers (no I/O — unit tested)
# ---------------------------------------------------------------------------- #

def scrub_secrets(text: Optional[str]) -> str:
    """Replace token-shaped substrings with [REDACTED]; preserve structure/whitespace."""
    if not text:
        return ""
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def detect_finishes(prev: Dict[str, str], curr: Dict[str, str]) -> List[str]:
    """Heads that completed a WORKING -> IDLE transition since the last cycle. Strictly
    edge-triggered: a head that was already idle (or unseen) last cycle never fires."""
    return [name for name, status in curr.items()
            if status == "idle" and prev.get(name) == "working"]


def task_signature(head: str, last_active: Optional[str], handoff: str) -> str:
    """A stable fingerprint of *this* finished task, for the loop-guard. Keyed on the head,
    the transcript's last-activity timestamp, and the handoff text itself — a worker blipping
    working/idle without producing a new turn keeps the same signature and is never re-notified."""
    h = hashlib.sha256()
    h.update(f"{head}\x00{last_active or ''}\x00{handoff[:600]}".encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def resolve_lead(room: str, leads: Dict[str, str]) -> Optional[str]:
    return leads.get(room)


def lead_pane(fleet: Dict[str, Any], lead: str) -> Tuple[Optional[str], Optional[str]]:
    """The lead head's live tmux pane id from the fleet snapshot, plus its status.
    Returns (None, status) when the lead exists but has no pane (offline/external)."""
    for h in fleet.get("heads") or []:
        if h.get("name") == lead:
            tmux = h.get("tmux") or {}
            return tmux.get("pane"), h.get("status")
    return None, None


def head_open_prs(fleet: Dict[str, Any], room: str, head: str) -> List[Dict[str, Any]]:
    """The worker's open PRs from the room's snapshot (branch->head matched by the collector)."""
    for r in fleet.get("rooms") or []:
        if r.get("id") == room:
            return [p for p in r.get("open_prs") or [] if p.get("head") == head]
    return []


def milestone_reached(nodes: List[Dict[str, Any]], milestone: str) -> Optional[bool]:
    """Is the armed milestone reached — i.e. is every checklist leaf BEFORE the
    ``{milestone:NAME}`` marker (document order) done? Walks the collector's fused roadmap tree.
    Returns None when the marker isn't on the roadmap at all (can't evaluate — caller warns and
    keeps running rather than halting on a typo'd name)."""
    leaves_before: List[bool] = []
    found = False

    def walk(ns: List[Dict[str, Any]]) -> bool:  # True = marker found, stop descending
        nonlocal found
        for n in ns:
            if (n.get("milestone") or "").strip().lower() == milestone.strip().lower():
                found = True
                return True
            if n.get("checked") is not None:
                leaves_before.append(n.get("status") == "done")
            if walk(n.get("children") or []):
                return True
        return False

    walk(nodes)
    if not found:
        return None
    return all(leaves_before)


def build_notify(
    worker: str, room: str, milestone: str, dispatch_n: int, cap: int,
    branch: Optional[str], ahead: int, last_commit: Optional[str],
    open_prs: List[Dict[str, Any]], handoff: str,
) -> str:
    """The exact message send-keys'd to the lead. Everything interpolated is already scrubbed;
    the whole thing is capped well under the console's INPUT_TEXT_MAX."""
    pr_lines = "\n".join(
        f"  - PR #{p.get('number')}: {p.get('title')}" for p in open_prs
    ) or "  - none open"
    body = (
        f"🛰️ [orchestrator] Worker '{worker}' finished a task in {room} "
        f"(autopilot → {milestone}, dispatch {dispatch_n}/{cap}).\n"
        f"Branch: {branch or '?'} ({ahead} ahead of main) · last commit: {last_commit or '—'}\n"
        f"Open PRs by {worker}:\n{pr_lines}\n"
        f"Handoff (its last assistant turn, scrubbed):\n"
        f"---\n{handoff or '(no transcript text found)'}\n---\n"
        f"You are the project lead. REVIEW this handoff (don't dispatch blind), then act: "
        f"queue/integrate as needed and SEND '{worker}' its next prompt toward milestone "
        f"{milestone} — or, if it looks stuck/erroring/done-with-the-milestone, escalate to "
        f"Schyler instead of re-dispatching into a wall. Code still flows through PRs; never "
        f"merge on its behalf without review."
    )
    if len(body) > NOTIFY_MAX_CHARS:
        body = body[: NOTIFY_MAX_CHARS - 1].rstrip() + "…"
    return body


def input_job(lead: str, pane: str, text: str, now: float) -> Dict[str, Any]:
    """Mirror of backend hq_console.input_job — the relay's expected shape, byte for byte."""
    return {"id": uuid.uuid4().hex[:12], "head": lead, "pane": pane, "text": text,
            "by": SENDER, "ts": int(now)}


def fresh_room_state(intent_ts: Any) -> Dict[str, Any]:
    return {"intent_ts": intent_ts, "dispatches": 0, "paused": None}


def room_state_for(state: Dict[str, Any], room: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    """This room's budget/pause slot, RESET whenever the arming intent changes (re-arming or
    moving the milestone = a fresh budget + clears any pause; that's the operator's reset knob)."""
    rooms = state.setdefault("rooms", {})
    rs = rooms.get(room)
    intent_ts = intent.get("requested_at")
    if not isinstance(rs, dict) or rs.get("intent_ts") != intent_ts:
        rs = fresh_room_state(intent_ts)
        rooms[room] = rs
    return rs


# ---------------------------------------------------------------------------- #
# I/O helpers (docker-exec redis-cli + host transcript reads — same as siblings)
# ---------------------------------------------------------------------------- #

def _redis(args: List[str], input_text: Optional[str] = None, timeout: float = 10.0) -> str:
    try:
        p = subprocess.run(
            ["docker", "exec", "-i", REDIS_CONTAINER, "redis-cli", *args],
            input=input_text, capture_output=True, text=True, timeout=timeout,
        )
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def get_json(key: str) -> Optional[Dict[str, Any]]:
    raw = _redis(["GET", key])
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def set_json(key: str, payload: Dict[str, Any], ttl_s: Optional[int] = None) -> bool:
    blob = json.dumps(payload, separators=(",", ":"))
    ok = _redis(["-x", "SET", key], input_text=blob) == "OK"
    if ok and ttl_s:
        _redis(["EXPIRE", key, str(ttl_s)])
    return ok


def rpush_capped(key: str, payload: Dict[str, Any], cap: int) -> None:
    _redis(["-x", "RPUSH", key], input_text=json.dumps(payload, separators=(",", ":")))
    _redis(["LTRIM", key, str(-cap), "-1"])


def stop_flagged(room: str) -> Optional[str]:
    """Which stop flag (if any) halts this room: 'global' | 'room' | None."""
    if _redis(["GET", STOP_KEY]):
        return "global"
    if _redis(["GET", STOP_PREFIX + room]):
        return "room"
    return None


def load_leads_and_cap() -> Tuple[Dict[str, str], int]:
    """Lead map + dispatch cap from the HQ org chart, baked-in defaults when absent/broken."""
    leads, cap = dict(DEFAULT_LEADS), DISPATCH_CAP
    try:
        with open(ROOMS_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        orch = cfg.get("orchestration") or {}
        if isinstance(orch.get("leads"), dict):
            leads.update({str(k): str(v) for k, v in orch["leads"].items()})
        if isinstance(orch.get("cap"), int) and orch["cap"] > 0:
            cap = orch["cap"]
    except (OSError, ValueError):
        pass
    return leads, cap


def transcript_dir_name(workdir: str) -> str:
    """Same slug mapping the collector uses (/ and _ both become -)."""
    return workdir.rstrip("/").replace("/", "-").replace("_", "-")


def latest_transcript(workdir: str) -> Optional[str]:
    d = os.path.join(PROJECTS, transcript_dir_name(workdir))
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return None
    return max(files, key=lambda p: os.path.getmtime(p)) if files else None


def read_handoff(workdir: Optional[str]) -> str:
    """The worker's handoff = the full text of its most recent assistant turn, scrubbed and
    capped. Unlike the collector's one-line ``current`` (160 chars), the lead needs the whole
    turn — that's where 'opened PR #N, needs review, suggest X next' lives."""
    if not workdir:
        return ""
    path = latest_transcript(workdir)
    if not path:
        return ""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > 400_000:
                f.seek(size - 400_000)
                f.readline()  # discard partial line
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    text = ""
    for line in tail.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    text = block["text"]
        elif isinstance(content, str) and content:
            text = content
    text = scrub_secrets(text).strip()
    if len(text) > HANDOFF_MAX_CHARS:
        text = text[: HANDOFF_MAX_CHARS - 1].rstrip() + "…"
    return text


# ---------------------------------------------------------------------------- #
# The cycle
# ---------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(f"[hq-orchestrator] {msg}")


def run_cycle(drive: bool) -> int:
    now = time.time()
    fleet = get_json(FLEET_KEY)
    if not fleet:
        log("no hq:fleet snapshot (collector not running?) — nothing to do")
        return 0

    leads, cap = load_leads_and_cap()
    state = get_json(STATE_KEY) or {}
    prev_status: Dict[str, str] = state.get("head_status") or {}
    handled: Dict[str, str] = state.setdefault("handled", {})

    heads = {h["name"]: h for h in fleet.get("heads") or [] if h.get("name")}
    curr_status = {name: h.get("status") or "offline" for name, h in heads.items()}
    finished = detect_finishes(prev_status, curr_status)

    audits: List[Dict[str, Any]] = []
    # heads whose handling must RETRY next cycle (lead unreachable): keep their prev status
    # 'working' so the same edge re-fires instead of being lost.
    retry_heads: set = set()

    def audit(kind: str, **kw: Any) -> None:
        entry = {"ts": int(now), "kind": kind, "dry_run": not drive, **kw}
        audits.append(entry)
        log(f"{kind} {json.dumps(kw, separators=(',', ':'))[:400]}")

    for name in finished:
        head = heads[name]
        room = head.get("room") or "?"
        if head.get("role") != "head":          # conductor / hq never get auto-dispatched
            continue
        lead = resolve_lead(room, leads)
        if not lead or name == lead:            # no lead configured, or the lead itself idled
            continue

        intent = get_json(AUTOPILOT_PREFIX + room)
        if not intent or not intent.get("milestone"):
            audit("skip-not-armed", head=name, room=room)
            continue
        milestone = intent["milestone"]
        rs = room_state_for(state, room, intent)

        flag = stop_flagged(room)
        if flag:
            audit("skip-stopped", head=name, room=room, flag=flag)
            continue
        if rs.get("paused"):
            audit("skip-paused", head=name, room=room, reason=rs["paused"].get("reason"))
            continue

        # milestone boundary — reaching the line Schyler drew halts + escalates, never overruns
        roadmap = get_json(ROADMAP_KEY) or {}
        nodes = ((roadmap.get("rooms") or {}).get(room) or {}).get("nodes") or []
        reached = milestone_reached(nodes, milestone)
        if reached is None:
            audit("warn-milestone-unknown", room=room, milestone=milestone)
        elif reached:
            rs["paused"] = {"reason": "milestone-reached", "milestone": milestone, "ts": int(now)}
            audit("pause-milestone-reached", head=name, room=room, milestone=milestone)
            continue

        handoff = read_handoff(head.get("workdir"))
        sig = task_signature(name, head.get("last_active"), handoff)
        if handled.get(name) == sig:
            audit("skip-loop-guard", head=name, room=room, sig=sig)
            continue

        if rs.get("dispatches", 0) >= cap:
            rs["paused"] = {"reason": "cap-reached", "cap": cap, "ts": int(now)}
            audit("pause-cap-reached", head=name, room=room, cap=cap)
            continue

        pane, lead_status = lead_pane(fleet, lead)
        if not pane or lead_status == "offline":
            retry_heads.add(name)   # keep the edge armed; retry when the lead is back
            audit("lead-unreachable", head=name, room=room, lead=lead, lead_status=lead_status)
            continue

        git = head.get("git") or {}
        msg = build_notify(
            worker=name, room=room, milestone=milestone,
            dispatch_n=rs.get("dispatches", 0) + 1, cap=cap,
            branch=head.get("branch"), ahead=git.get("ahead") or 0,
            last_commit=git.get("last_commit"),
            open_prs=head_open_prs(fleet, room, name), handoff=handoff,
        )
        job = input_job(lead, pane, msg, now)

        if drive:
            _redis(["-x", "RPUSH", INPUT_QUEUE], input_text=json.dumps(job, separators=(",", ":")))
            audit("dispatch", head=name, room=room, lead=lead, pane=pane, job_id=job["id"],
                  sig=sig, n=rs.get("dispatches", 0) + 1, cap=cap)
        else:
            audit("would-dispatch", head=name, room=room, lead=lead, pane=pane, sig=sig,
                  n=rs.get("dispatches", 0) + 1, cap=cap)
            log("DRY-RUN message that would be sent:\n" + msg)
        # budget + loop-guard advance in BOTH modes so the whole loop (incl. cap-pause) can be
        # verified end-to-end in dry-run before --drive is ever given.
        rs["dispatches"] = rs.get("dispatches", 0) + 1
        handled[name] = sig

    # persist: statuses advance for everyone except retry-pending heads (their edge stays armed)
    new_status = dict(curr_status)
    for name in retry_heads:
        new_status[name] = prev_status.get(name, "working")
    state["head_status"] = new_status
    set_json(STATE_KEY, state)

    for entry in audits:
        rpush_capped(AUDIT_KEY, entry, AUDIT_MAX)

    set_json(STATUS_KEY, {
        "generated_at": int(now),
        "mode": "live" if drive else "dry-run",
        "cap": cap,
        "leads": leads,
        "finished_this_cycle": finished,
        "rooms": state.get("rooms") or {},
    }, ttl_s=STATUS_TTL_S)

    if finished:
        log(f"cycle done — finishes={finished} audits={len(audits)} mode={'LIVE' if drive else 'dry-run'}")
    return 0


def main() -> int:
    drive = "--drive" in sys.argv[1:] or os.getenv("HQ_ORCH_DRIVE") == "1"
    return run_cycle(drive)


if __name__ == "__main__":
    raise SystemExit(main())
