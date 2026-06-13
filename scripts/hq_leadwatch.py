#!/usr/bin/env python3
"""Hydra HQ leadwatch — the director's done/stuck awareness monitor (sibling of hq_orchestrator.py).

A project lead (per ORCHESTRATION.md `orchestration.leads`) needs to KNOW when a head it tasked
finishes or stalls — without committing to full auto-dispatch. The orchestrator is the *autopilot*
(detect→dispatch, armed-only); this is pure *awareness* (notify-only, always-on). They're complements:
use leadwatch when heads bring work back for review (no auto-next-prompt); use the orchestrator when a
room is armed for autonomous milestone runs.

This runs on the HOST (same single-cycle/supervising-loop + docker-exec-redis pattern as the collector)
and, 0-token while quiet, watches every WORKER head in a led room off the collector's ``hq:fleet`` and
pings that room's LEAD when a worker:

  - DONE     — WORKING -> IDLE: the worker finished a turn. Lead gets the handoff (its last assistant
               turn, scrubbed) to review.
  - STUCK    — one of:
               * blocked on a permission/menu prompt (collector status ``waiting-input``) for >=
                 STUCK_WAIT_CYCLES consecutive cycles (transients ignored);
               * WORKING -> OFFLINE (crashed/died mid-task).
               (Rate-limit caps are hq_ratewatch.py's job — not duplicated here.)

Notification rides the SAME bounded path the console + orchestrator use: an ``input_job`` RPUSHed to
``hq:input:queue`` -> the relay send-keys it into the lead's pane (so a Weaver-led alert lands in
Weaver's own session, where it can act). STUCK also pings Schyler via the SIGNAL_BOT_* Telegram path,
since a stalled head may need a human.

NOTIFY-ONLY: leadwatch NEVER sends a worker its next prompt. Detection + routing = 0-token; the lead does
the reasoning (review / unblock / re-task). Guardrails mirror the siblings: DRY-RUN DEFAULT (--drive /
HQ_LEADWATCH_DRIVE=1), a per-(head,event) dedup so one finish/stall pings once, a global stop flag.

Install:  cp scripts/hq_leadwatch.py ~/.local/bin/hq-leadwatch.py
Run:      while :; do python3 ~/.local/bin/hq-leadwatch.py; sleep 20; done   (one cycle/exec)

Security: same posture as the siblings — only DERIVED, REDACTED text leaves the host, via the
already-audited console input path. The pure helpers below are unit-tested in test_hq_leadwatch.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
REDIS_CONTAINER = os.getenv("HQ_REDIS_CONTAINER", "tdbox-redis")

FLEET_KEY = "hq:fleet"                       # collector's snapshot (status/pane/workdir/role/last_active)
STATE_KEY = "hq:leadwatch:state"             # cross-cycle memory (prev statuses, dedup, wait counters)
STATUS_KEY = "hq:leadwatch:status"           # what HQ surfaces (mode, last events)
AUDIT_KEY = "hq:leadwatch:audit"             # capped list of every decision
STOP_KEY = "hq:leadwatch:stop"               # global kill switch (any value = stop)
INPUT_QUEUE = "hq:input:queue"               # the console's bounded input path (relay consumes)
AUDIT_MAX = 500
STATUS_TTL_S = 600

ROOMS_CONFIG_PATH = os.getenv("HQ_ROOMS_CONFIG", os.path.join(HOME, "hydra-hq", "rooms.config.json"))
SENDER = "hq-leadwatch"
HANDOFF_MAX_CHARS = 1200            # handoff slice shipped to the lead
NOTIFY_MAX_CHARS = 6000            # < console INPUT_TEXT_MAX
STUCK_WAIT_CYCLES = int(os.getenv("HQ_LEADWATCH_STUCK_CYCLES", "2"))   # waiting-input cycles before "stuck"
WATCH_SKIP_ROLES = frozenset({"hq", "conductor"})   # report to Command/Charlotte, not a project lead

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
    if not text:
        return ""
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def detect_done(prev: Dict[str, str], curr: Dict[str, str]) -> List[str]:
    """Heads that completed a WORKING -> IDLE edge since last cycle. Edge-triggered: a head already
    idle (or first-seen) never fires."""
    return [n for n, s in curr.items() if s == "idle" and prev.get(n) == "working"]


def detect_crashed(prev: Dict[str, str], curr: Dict[str, str]) -> List[str]:
    """Heads that went WORKING -> OFFLINE (died mid-task)."""
    return [n for n, s in curr.items() if s == "offline" and prev.get(n) == "working"]


def update_wait_counters(prev_counts: Dict[str, int], curr: Dict[str, str]) -> Dict[str, int]:
    """Per-head consecutive ``waiting-input`` cycle count; resets to 0 the moment a head isn't
    waiting. (A head blocked on a permission/menu prompt is 'stuck' once it persists.)"""
    out: Dict[str, int] = {}
    for n, s in curr.items():
        out[n] = (prev_counts.get(n, 0) + 1) if s == "waiting-input" else 0
    return out


def newly_stuck_waiting(wait_counts: Dict[str, int], threshold: int) -> List[str]:
    """Heads that have *just* crossed the stuck threshold (== threshold), so we fire exactly once
    per stall, not every cycle while it stays blocked."""
    return [n for n, c in wait_counts.items() if c == threshold]


def event_signature(head: str, kind: str, marker: str) -> str:
    """Dedup key: one ping per (head, event, marker). `marker` is the last-active stamp / handoff /
    prompt — so a NEW finish (new turn) re-fires, the same one doesn't."""
    h = hashlib.sha256(f"{head}\x00{kind}\x00{marker or ''}".encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def resolve_lead(room: str, leads: Dict[str, str]) -> Optional[str]:
    return leads.get(room)


def lead_pane(fleet: Dict[str, Any], lead: str) -> Tuple[Optional[str], Optional[str]]:
    for h in fleet.get("heads") or []:
        if h.get("name") == lead:
            return (h.get("tmux") or {}).get("pane"), h.get("status")
    return None, None


def build_done_msg(worker: str, room: str, handoff: str) -> str:
    body = (f"✅ [leadwatch] '{worker}' ({room}) finished a turn — REVIEW its handoff and decide next "
            f"(it's awaiting you; leadwatch does not auto-dispatch).\n"
            f"Handoff (last assistant turn, scrubbed):\n---\n{handoff or '(no transcript text)'}\n---")
    return body[: NOTIFY_MAX_CHARS - 1] + "…" if len(body) > NOTIFY_MAX_CHARS else body


def build_stuck_msg(worker: str, room: str, reason: str, detail: str) -> str:
    body = (f"⚠️ [leadwatch] '{worker}' ({room}) looks STUCK — {reason}. It needs you to unblock or "
            f"re-task it (leadwatch does not act for you).\nDetail: {detail or '(none)'}")
    return body[: NOTIFY_MAX_CHARS - 1] + "…" if len(body) > NOTIFY_MAX_CHARS else body


def input_job(head: str, pane: str, text: str, now: float, jid: str) -> Dict[str, Any]:
    """Mirror of backend hq_console.input_job — the relay's expected shape, byte for byte."""
    return {"id": jid, "head": head, "pane": pane, "text": text, "by": SENDER, "ts": int(now)}


# ---------------------------------------------------------------------------- #
# I/O helpers (docker-exec redis-cli + host transcript reads — sibling pattern)
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
    ok = _redis(["-x", "SET", key], input_text=json.dumps(payload, separators=(",", ":"))) == "OK"
    if ok and ttl_s:
        _redis(["EXPIRE", key, str(ttl_s)])
    return ok


def rpush_capped(key: str, payload: Dict[str, Any], cap: int) -> None:
    _redis(["-x", "RPUSH", key], input_text=json.dumps(payload, separators=(",", ":")))
    _redis(["LTRIM", key, str(-cap), "-1"])


def stop_flagged() -> bool:
    return bool(_redis(["GET", STOP_KEY]))


def load_leads() -> Dict[str, str]:
    """The per-room lead map from the HQ org chart (rooms.config.json `orchestration.leads`) — the
    SAME key the orchestrator + collector read. Empty/absent => nothing watched."""
    try:
        with open(ROOMS_CONFIG_PATH, "r", encoding="utf-8") as f:
            orch = (json.load(f) or {}).get("orchestration") or {}
        leads = orch.get("leads")
        return {str(k): str(v) for k, v in leads.items()} if isinstance(leads, dict) else {}
    except (OSError, ValueError):
        return {}


def transcript_dir_name(workdir: str) -> str:
    return workdir.rstrip("/").replace("/", "-").replace("_", "-")


def read_handoff(workdir: Optional[str]) -> str:
    """The worker's last assistant turn (scrubbed, capped) — same transcript-tail read as the
    orchestrator's read_handoff."""
    if not workdir:
        return ""
    d = os.path.join(PROJECTS, transcript_dir_name(workdir))
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return ""
    if not files:
        return ""
    path = max(files, key=lambda p: os.path.getmtime(p))
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > 400_000:
                f.seek(size - 400_000)
                f.readline()
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    text = ""
    for line in tail.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    text = block["text"]
        elif isinstance(content, str) and content:
            text = content
    text = scrub_secrets(text).strip()
    return text[: HANDOFF_MAX_CHARS - 1] + "…" if len(text) > HANDOFF_MAX_CHARS else text


def notify_schyler(text: str) -> bool:
    """Telegram via SIGNAL_BOT_* (stdlib). Degrades to a log + the hq:leadwatch:status flag."""
    token, chat = os.getenv("SIGNAL_BOT_TOKEN"), os.getenv("SIGNAL_BOT_CHAT_ID")
    if not token or not chat:
        log(f"telegram (no creds, not sent): {text}")
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        log(f"telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------- #
# The cycle
# ---------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(f"[hq-leadwatch] {msg}")


def _notify_lead(lead: str, pane: str, text: str, drive: bool, now: float, audit: Any, kind: str) -> None:
    jid = hashlib.sha256(f"{lead}{text[:40]}{now}".encode()).hexdigest()[:12]
    if drive:
        job = input_job(lead, pane, text, now, jid)
        _redis(["-x", "RPUSH", INPUT_QUEUE], input_text=json.dumps(job, separators=(",", ":")))
        audit(kind, lead=lead, pane=pane, job_id=jid)
    else:
        audit("would-" + kind, lead=lead, pane=pane)
        log(f"DRY-RUN would notify lead {lead} @ {pane}:\n{text}")


def run_cycle(drive: bool) -> int:
    now = time.time()
    audits: List[Dict[str, Any]] = []

    def audit(kind: str, **kw: Any) -> None:
        entry = {"ts": int(now), "kind": kind, "dry_run": not drive, **kw}
        audits.append(entry)
        log(f"{kind} {json.dumps(kw, separators=(',', ':'))[:300]}")

    state = get_json(STATE_KEY) or {}
    if stop_flagged():
        audit("skip-stopped")
        _flush(audits, state, now, drive, stopped=True)
        return 0

    fleet = get_json(FLEET_KEY)
    if not fleet:
        audit("no-fleet")
        _flush(audits, state, now, drive)
        return 0

    leads = load_leads()
    heads = {h["name"]: h for h in fleet.get("heads") or [] if h.get("name")}
    prev_status: Dict[str, str] = state.get("head_status") or {}
    handled: Dict[str, str] = state.setdefault("handled", {})

    # only WORKER heads in a LED room are watched; the lead itself is never watched, and
    # hq/conductor-role heads are excluded — they live in a project repo (so room-lead resolves)
    # but report to Command/Charlotte, not the project lead, so the lead shouldn't be pinged on them.
    watched = {n: h for n, h in heads.items()
               if resolve_lead(h.get("room") or "", leads)
               and h.get("name") != leads.get(h.get("room") or "")
               and h.get("role") not in WATCH_SKIP_ROLES}
    curr_status = {n: h.get("status") or "offline" for n, h in watched.items()}

    wait_counts = update_wait_counters(state.get("wait_counts") or {}, curr_status)

    def lead_for(name: str) -> Tuple[Optional[str], Optional[str]]:
        room = (watched[name].get("room") or "")
        lead = resolve_lead(room, leads)
        pane, lstatus = lead_pane(fleet, lead) if lead else (None, None)
        return lead, pane if (pane and lstatus != "offline") else None

    # ---- DONE ----
    for name in detect_done(prev_status, curr_status):
        handoff = read_handoff(watched[name].get("workdir"))
        sig = event_signature(name, "done", (watched[name].get("last_active") or "") + handoff[:200])
        if handled.get(name + ":done") == sig:
            continue
        handled[name + ":done"] = sig
        room = watched[name].get("room") or "?"
        lead, pane = lead_for(name)
        if not lead:
            continue
        if pane:
            _notify_lead(lead, pane, build_done_msg(name, room, handoff), drive, now, audit, "done")
        else:
            audit("done-lead-unreachable", head=name, room=room, lead=lead)

    # ---- STUCK: crashed mid-task ----
    for name in detect_crashed(prev_status, curr_status):
        sig = event_signature(name, "offline", watched[name].get("last_active") or str(int(now)))
        if handled.get(name + ":offline") == sig:
            continue
        handled[name + ":offline"] = sig
        room = watched[name].get("room") or "?"
        lead, pane = lead_for(name)
        msg = build_stuck_msg(name, room, "it went OFFLINE mid-task (possible crash)",
                              watched[name].get("current") or "")
        if lead and pane:
            _notify_lead(lead, pane, msg, drive, now, audit, "stuck-offline")
        notify_schyler(f"⚠️ leadwatch: '{name}' ({room}) went offline mid-task — may have crashed.") if drive else None

    # ---- STUCK: blocked on a prompt (sustained) ----
    for name in newly_stuck_waiting(wait_counts, STUCK_WAIT_CYCLES):
        detail = watched[name].get("current") or "blocked on a permission/menu prompt"
        sig = event_signature(name, "waiting", detail[:200])
        if handled.get(name + ":waiting") == sig:
            continue
        handled[name + ":waiting"] = sig
        room = watched[name].get("room") or "?"
        lead, pane = lead_for(name)
        msg = build_stuck_msg(name, room, f"blocked on a prompt for {STUCK_WAIT_CYCLES}+ cycles", detail)
        if lead and pane:
            _notify_lead(lead, pane, msg, drive, now, audit, "stuck-waiting")
        if drive:
            notify_schyler(f"⚠️ leadwatch: '{name}' ({room}) is blocked waiting for input — needs an answer.")
    # clear the waiting dedup once a head is no longer waiting, so the NEXT stall re-fires
    for name, s in curr_status.items():
        if s != "waiting-input":
            handled.pop(name + ":waiting", None)

    state["head_status"] = curr_status
    state["wait_counts"] = wait_counts
    _flush(audits, state, now, drive)
    return 0


def _flush(audits: List[Dict[str, Any]], state: Dict[str, Any], now: float, drive: bool,
           stopped: bool = False) -> None:
    set_json(STATE_KEY, state)
    for entry in audits:
        rpush_capped(AUDIT_KEY, entry, AUDIT_MAX)
    set_json(STATUS_KEY, {"generated_at": int(now), "mode": "live" if drive else "dry-run",
                          "stopped": stopped, "events_this_cycle": len(audits)}, ttl_s=STATUS_TTL_S)
    if audits:
        log(f"cycle done — events={len(audits)} mode={'LIVE' if drive else 'dry-run'}")


def main() -> int:
    drive = "--drive" in sys.argv[1:] or os.getenv("HQ_LEADWATCH_DRIVE") == "1"
    return run_cycle(drive)


if __name__ == "__main__":
    raise SystemExit(main())
