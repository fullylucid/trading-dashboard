#!/usr/bin/env python3
"""Hydra HQ ratewatch — fleet rate-drop auto-resume detector (sibling of hq_orchestrator.py).

The Max-plan usage cap is ACCOUNT-WIDE, not per-head: when it hits, every working head stalls
at the same instant. This script runs on the HOST (same single-cycle/supervising-loop +
docker-exec-redis pattern as hq_collector.py / hq_orchestrator.py) and:

1. WATCHES the binding usage window off ``claude:usage`` (published every ~5min by
   ~/.local/bin/claude-usage.sh). When the binding window's utilization crosses ``cap_pct``,
2. CONFIRMS the cap is real by grepping the tmux panes of currently-working heads for the
   "usage limit reached / limit will reset" line — the pane-grep is GROUND TRUTH (the OAuth
   usage endpoint exposes no hard 'limited' flag, only a utilization %). Requiring the pane
   line also transparently absorbs ``extra_usage`` spillover (pct can read ~100 without a real
   cap; with no cap line in any pane, we never fire).
3. SNAPSHOTS which heads were status=working (from the collector's ``hq:fleet`` snapshot) and
   the binding window's authoritative ``resets_at``, then WAITS until ``resets_at + buffer``.
4. RESUMES each snapshotted head with a NUDGE (not a re-send of the original prompt — their
   ``--continue`` context still holds the half-done work; re-sending risks restarting). Resume
   is PLUGGABLE per head: WSL/tmux heads via the console ``hq:input:queue`` relay; external
   heads (win-gaia, no tmux) via the gaia-bus console channel the hq head is building.

Guardrails (mirror hq_orchestrator.py — autonomy is bounded + reviewable):
- DRY-RUN DEFAULT:  nothing touches hq:input:queue until ``--drive`` / HQ_RATEWATCH_DRIVE=1.
                    Every detection + the exact nudge it WOULD send is logged + audited, and the
                    full WATCHING→CAPPED→RESUMING cycle advances in dry-run so it's reviewable.
- STOP flag:        ``hq:ratewatch:stop`` (global) or ``hq:ratewatch:stop:<head>`` (per-head).
- LOOP-GUARD:       a head that re-caps on the SAME task_signature it was just resumed on (zero
                    progress — a task too big for one window) backs off + escalates, never spins.
- MAX-RESUMES:      per head, ``max_resumes_per_window`` nudges per binding-reset cycle (default 1).
- WEEKLY ESCALATE:  a weekly (7-day) cap is days out — never auto-sleep that long; escalate + HOLD.
- ESCALATE:         a head still not working N cycles post-nudge, a re-cap, or a weekly cap pings
                    Schyler via the existing SIGNAL_BOT_* Telegram path + flags hq:ratewatch:status.

Install:  cp scripts/hq_ratewatch.py ~/.local/bin/hq-ratewatch.py
Run:      while :; do python3 ~/.local/bin/hq-ratewatch.py; sleep 30; done   (one cycle/exec)

Security: same posture as the siblings — only DERIVED, REDACTED text leaves the host, via the
already-audited console input path (the relay validates the pane against the live hydra session
and never evals payloads). The pure helpers below are unit-tested in test_hq_ratewatch.py.
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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
REDIS_CONTAINER = os.getenv("HQ_REDIS_CONTAINER", "tdbox-redis")

USAGE_KEY = "claude:usage"                  # claude-usage.sh publishes here (session/weekly pct + resets)
FLEET_KEY = "hq:fleet"                       # collector's snapshot (statuses, panes, workdir, git)
STATE_KEY = "hq:ratewatch:state"             # cross-cycle state machine + snapshot + loop-guard sigs
STATUS_KEY = "hq:ratewatch:status"           # what HQ surfaces (phase, resuming_at, countdown, heads)
AUDIT_KEY = "hq:ratewatch:audit"             # capped list of every decision this script makes
STOP_KEY = "hq:ratewatch:stop"               # global kill switch (any value = stop)
STOP_PREFIX = "hq:ratewatch:stop:"           # per-head kill switch
INPUT_QUEUE = "hq:input:queue"               # the console's bounded input path (relay consumes)
AUDIT_MAX = 500
STATUS_TTL_S = 600

ROOMS_CONFIG_PATH = os.getenv("HQ_ROOMS_CONFIG", os.path.join(HOME, "hydra-hq", "rooms.config.json"))
SENDER = "hq-ratewatch"
NUDGE_MAX_CHARS = 6000          # well under the console INPUT_TEXT_MAX (10000)
HANDOFF_SIG_CHARS = 600         # slice of the handoff that feeds the loop-guard signature
PANE_CAPTURE_LINES = 80         # capture-pane scrollback depth for the cap-line grep

# Defaults (overridable via rooms.config.json "ratewatch"; see load_config).
DEFAULTS: Dict[str, Any] = {
    "cap_pct": 99.0,
    "buffer_s": 60,
    "max_resumes_per_window": 1,
    "weekly_cap_escalate_only": True,
    "stuck_cycles_before_escalate": 6,
    "external_heads": {"win-gaia": "bus"},
}

# The usage windows in claude:usage, by display name -> (pct key, resets-at key). The "binding"
# window each cycle is whichever is at the highest utilization.
WINDOWS: List[Tuple[str, str, str]] = [
    ("session", "session_pct", "session_resets_at"),   # five_hour — resets in hours
    ("weekly", "weekly_pct", "weekly_resets_at"),       # seven_day — resets in DAYS (escalate-only)
    ("sonnet", "sonnet_pct", "sonnet_resets_at"),       # seven_day_sonnet
]
WEEKLY_WINDOWS = frozenset({"weekly", "sonnet"})

# The stall line Claude Code prints when the cap hits. Tolerant + configurable — confirm the exact
# wording against a real capped pane before flipping --drive (the one piece not yet seen live).
CAP_LINE_RE = re.compile(
    r"(?i)(usage limit reached|limit will reset|approaching your usage limit|/upgrade to increase)"
)

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


def binding_window(usage: Dict[str, Any]) -> Tuple[Optional[str], float, Optional[str]]:
    """The window at the highest utilization — the one that will cap first / is capping.
    Returns (name, pct, resets_at), or (None, 0.0, None) when no window has a numeric pct."""
    usable: List[Tuple[str, float, Optional[str]]] = []
    for name, pk, rk in WINDOWS:
        p = usage.get(pk)
        if isinstance(p, (int, float)):
            usable.append((name, float(p), usage.get(rk)))
    if not usable:
        return (None, 0.0, None)
    return max(usable, key=lambda w: w[1])


def over_threshold(usage: Dict[str, Any], cap_pct: float) -> bool:
    """Is the binding window at/over the cap threshold? (the trigger, not the confirmation)."""
    _, pct, _ = binding_window(usage)
    return pct >= cap_pct


def cap_confirmed(pane_texts: List[str]) -> bool:
    """Ground truth: does any stalled head's captured pane carry the cap line?"""
    return any(CAP_LINE_RE.search(t or "") for t in pane_texts)


def is_capped(usage: Dict[str, Any], cap_pct: float, pane_texts: List[str]) -> bool:
    """Enter CAPPED only when the binding pct is over threshold AND a stalled pane confirms it.
    The pane-grep is ground truth — this also transparently handles extra_usage spillover (pct can
    read ~100 with no real cap; absent a cap line in any pane, cap_confirmed stays False)."""
    return over_threshold(usage, cap_pct) and cap_confirmed(pane_texts)


def is_weekly(window_name: Optional[str]) -> bool:
    """A 7-day window (resets days out) — escalate, never auto-sleep that long."""
    return window_name in WEEKLY_WINDOWS


def snapshot_working(fleet: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The named heads that were status=working at cap time (the resume set)."""
    return [h for h in (fleet.get("heads") or [])
            if h.get("status") == "working" and h.get("name")]


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def seconds_until(resets_at_iso: Optional[str], buffer_s: int, now: float) -> Optional[int]:
    """Seconds from epoch ``now`` until ``resets_at`` + buffer. <=0 means the wait is over.
    Returns None when the timestamp is missing/unparseable — the caller HOLDS + escalates rather
    than resuming on bad data (authoritative reset time, never pane-scraped)."""
    dt = parse_iso(resets_at_iso)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() + buffer_s - now)


def resets_after(resets_at_iso: Optional[str], buffer_s: int, now: float) -> bool:
    s = seconds_until(resets_at_iso, buffer_s, now)
    return s is not None and s <= 0


def task_signature(head: str, last_active: Optional[str], handoff: str) -> str:
    """Stable fingerprint of the task a head was on, for the loop-guard. Keyed on head + the
    transcript's last-activity stamp + the handoff text — a head resumed and re-capped having made
    ZERO progress keeps the same signature (so we back off); real progress changes it."""
    h = hashlib.sha256()
    h.update(f"{head}\x00{last_active or ''}\x00{(handoff or '')[:HANDOFF_SIG_CHARS]}".encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def resume_target(head: Dict[str, Any], external_map: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """How to nudge this head (pluggable). A tmux pane => ('tmux', pane). Else a known external
    head => (channel, name), e.g. ('bus', 'win-gaia'). Else None (paneless + unknown => skip)."""
    pane = (head.get("tmux") or {}).get("pane")
    if pane:
        return ("tmux", pane)
    name = head.get("name")
    channel = external_map.get(name) if name else None
    if channel:
        return (channel, name)
    return None


def build_nudge() -> str:
    """The resume NUDGE — deliberately NOT the original prompt (the head's --continue context
    still holds the half-done work; re-sending risks restarting from scratch)."""
    return ("⏳ [ratewatch] The Claude usage limit that paused you has reset — resume the task you "
            "were on. Your --continue context is intact; don't restart from scratch.")


def should_backoff(prev_sig: Optional[str], new_sig: str, resumes_done: int, max_resumes: int) -> bool:
    """Loop-guard: skip a head when it re-capped on the SAME signature it was just resumed on
    (zero progress), or when it's already been resumed max_resumes times this window."""
    if prev_sig is not None and prev_sig == new_sig:
        return True
    return resumes_done >= max_resumes


def input_job(head: str, pane: str, text: str, now: float, jid: str) -> Dict[str, Any]:
    """Mirror of backend hq_console.input_job — the relay's expected shape, byte for byte."""
    return {"id": jid, "head": head, "pane": pane, "text": text, "by": SENDER, "ts": int(now)}


# ---------------------------------------------------------------------------- #
# I/O helpers (docker-exec redis-cli + tmux + host transcript reads — sibling pattern)
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


def stop_flagged(head: Optional[str] = None) -> Optional[str]:
    """Which stop flag (if any) is set: 'global' | 'head' | None."""
    if _redis(["GET", STOP_KEY]):
        return "global"
    if head and _redis(["GET", STOP_PREFIX + head]):
        return "head"
    return None


def load_config() -> Dict[str, Any]:
    """ratewatch config from the HQ org chart (rooms.config.json "ratewatch"), defaults filled in."""
    cfg = dict(DEFAULTS)
    try:
        with open(ROOMS_CONFIG_PATH, "r", encoding="utf-8") as f:
            user = (json.load(f) or {}).get("ratewatch") or {}
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if v is not None})
    except (OSError, ValueError):
        pass
    if not isinstance(cfg.get("external_heads"), dict):
        cfg["external_heads"] = dict(DEFAULTS["external_heads"])
    return cfg


def capture_pane(pane: str) -> str:
    """Last PANE_CAPTURE_LINES of a tmux pane's visible+scrollback text (for the cap-line grep)."""
    try:
        p = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", f"-{PANE_CAPTURE_LINES}", "-t", pane],
            capture_output=True, text=True, timeout=8,
        )
        return p.stdout if p.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def transcript_dir_name(workdir: str) -> str:
    return workdir.rstrip("/").replace("/", "-").replace("_", "-")


def latest_transcript(workdir: str) -> Optional[str]:
    d = os.path.join(PROJECTS, transcript_dir_name(workdir))
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return None
    return max(files, key=lambda p: os.path.getmtime(p)) if files else None


def read_handoff(workdir: Optional[str]) -> str:
    """The head's last assistant turn (scrubbed) — feeds the loop-guard signature only. Same
    transcript-tail read as hq_orchestrator.read_handoff."""
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
                f.readline()
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
    return scrub_secrets(text).strip()


def notify_schyler(text: str) -> bool:
    """Escalate to Schyler via the existing SIGNAL_BOT_* Telegram path (stdlib, no requests).
    Degrades gracefully: no creds => log + rely on the hq:ratewatch:status flag HQ surfaces."""
    token = os.getenv("SIGNAL_BOT_TOKEN")
    chat = os.getenv("SIGNAL_BOT_CHAT_ID")
    if not token or not chat:
        log(f"escalation (no SIGNAL_BOT creds, not sent): {text}")
        return False
    try:
        body = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        log(f"escalation send failed: {e}")
        return False


# ---------------------------------------------------------------------------- #
# The cycle
# ---------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(f"[hq-ratewatch] {msg}")


def _enqueue_nudge(head: str, kind: str, target: str, drive: bool, now: float,
                   audit: Any, external_map: Dict[str, str]) -> None:
    """Deliver (or in dry-run, log) the resume nudge to one head, by its resume strategy."""
    nudge = build_nudge()
    if len(nudge) > NUDGE_MAX_CHARS:
        nudge = nudge[: NUDGE_MAX_CHARS - 1] + "…"
    if kind == "tmux":
        jid = hashlib.sha256(f"{head}{now}".encode()).hexdigest()[:12]
        job = input_job(head, target, nudge, now, jid)
        if drive:
            _redis(["-x", "RPUSH", INPUT_QUEUE], input_text=json.dumps(job, separators=(",", ":")))
            audit("resume-tmux", head=head, pane=target, job_id=jid)
        else:
            audit("would-resume-tmux", head=head, pane=target)
            log(f"DRY-RUN would nudge {head} @ {target}: {nudge}")
    elif kind == "bus":
        # External head (win-gaia): resume via the gaia-bus console channel the hq head is
        # building. Stubbed until that lands — pluggable so it slots in without touching the cycle.
        audit("resume-bus-stub", head=head, channel=kind, drive=drive)
        log(f"{'(drive) ' if drive else 'DRY-RUN '}would nudge external head {head} via bus (channel not yet wired)")
    else:
        audit("resume-skip-unknown-target", head=head, kind=kind)


def _do_resume(state: Dict[str, Any], cfg: Dict[str, Any], drive: bool, now: float, audit: Any) -> Dict[str, Any]:
    """Fire the nudges for the snapshotted heads, then reset to WATCHING with a loop-guard record
    of what was resumed on which signature (so a same-sig re-cap next window backs off)."""
    snapshot = state.get("snapshot") or []
    external_map = cfg["external_heads"]
    resumes = state.get("resumes") or {}
    last_sigs: Dict[str, str] = {}
    resumed: List[str] = []
    for s in snapshot:
        head = s.get("name")
        last_sigs[head] = s.get("sig")
        if stop_flagged(head):
            audit("resume-skip-stopped", head=head)
            continue
        if s.get("backoff"):
            audit("resume-skip-loop-guard", head=head, sig=s.get("sig"))
            continue
        if resumes.get(head, 0) >= cfg["max_resumes_per_window"]:
            audit("resume-skip-max", head=head, max=cfg["max_resumes_per_window"])
            continue
        target = s.get("target")
        if not target:
            audit("resume-skip-no-target", head=head)
            continue
        _enqueue_nudge(head, target[0], target[1], drive, now, audit, external_map)
        resumes[head] = resumes.get(head, 0) + 1
        resumed.append(head)
    notify_schyler(
        f"🛰️ ratewatch: fleet usage cap cleared (binding={state.get('binding')}, "
        f"capped {_hhmm(state.get('capped_at'))}→{_hhmm(now)}). "
        f"Resumed {len(resumed)} head(s): {', '.join(resumed) or 'none'}."
    )
    return {
        "phase": "WATCHING",
        "last_window": {"sigs": last_sigs, "resumed": resumed, "resumed_at": int(now),
                        "binding": state.get("binding")},
        # pending-return tracker: nudged heads we expect to flip back to working
        "pending": {h: {"resumed_at": int(now), "cycles": 0} for h in resumed},
    }


def _hhmm(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return "?"


def _check_pending(state: Dict[str, Any], heads: Dict[str, Any], cfg: Dict[str, Any],
                   now: float, audit: Any) -> None:
    """A resumed head that never returns to working within stuck_cycles ⇒ escalate (it may be
    stuck on an error, not a cap). Cleared as soon as it's working again."""
    pending = state.get("pending") or {}
    if not pending:
        return
    limit = int(cfg["stuck_cycles_before_escalate"])
    for head in list(pending.keys()):
        status = (heads.get(head) or {}).get("status")
        if status == "working":
            audit("pending-cleared", head=head)
            pending.pop(head, None)
            continue
        pending[head]["cycles"] = pending[head].get("cycles", 0) + 1
        if pending[head]["cycles"] >= limit:
            audit("escalate-stuck", head=head, cycles=pending[head]["cycles"])
            notify_schyler(f"⚠️ ratewatch: '{head}' was nudged after the cap reset but is still not "
                           f"working after {pending[head]['cycles']} cycles — may be stuck. Please check.")
            pending.pop(head, None)
    state["pending"] = pending


def run_cycle(drive: bool) -> int:
    now = time.time()
    cfg = load_config()
    state = get_json(STATE_KEY) or {"phase": "WATCHING"}
    phase = state.get("phase", "WATCHING")

    audits: List[Dict[str, Any]] = []

    def audit(kind: str, **kw: Any) -> None:
        entry = {"ts": int(now), "kind": kind, "dry_run": not drive, **kw}
        audits.append(entry)
        log(f"{kind} {json.dumps(kw, separators=(',', ':'))[:400]}")

    if stop_flagged():
        audit("skip-stopped-global")
        _flush(audits, state, phase, now, drive, cfg, extra={"stopped": True})
        return 0

    fleet = get_json(FLEET_KEY) or {}
    heads = {h["name"]: h for h in fleet.get("heads") or [] if h.get("name")}

    if phase == "WATCHING":
        _check_pending(state, heads, cfg, now, audit)
        usage = get_json(USAGE_KEY)
        if not usage:
            audit("no-usage-data")
        elif not over_threshold(usage, cfg["cap_pct"]):
            pass  # the common, silent, 0-token path
        else:
            working = snapshot_working(fleet)
            pane_texts = [capture_pane((h.get("tmux") or {}).get("pane"))
                          for h in working if (h.get("tmux") or {}).get("pane")]
            name, pct, resets_at = binding_window(usage)
            if not cap_confirmed(pane_texts):
                # pct high but no stalled pane confirms it (spillover, or the line scrolled off) —
                # stay in WATCHING rather than mis-fire. The safe failure mode.
                audit("over-threshold-unconfirmed", binding=name, pct=pct, working=len(working))
            else:
                prev = (state.get("last_window") or {}).get("sigs") or {}
                resumes_prev = {}  # fresh window
                snap = []
                for h in working:
                    handoff = read_handoff(h.get("workdir"))
                    sig = task_signature(h["name"], h.get("last_active"), handoff)
                    backoff = should_backoff(prev.get(h["name"]), sig,
                                             resumes_prev.get(h["name"], 0),
                                             cfg["max_resumes_per_window"])
                    snap.append({"name": h["name"], "sig": sig, "room": h.get("room"),
                                 "target": resume_target(h, cfg["external_heads"]), "backoff": backoff})
                    if backoff:
                        audit("loop-guard-backoff", head=h["name"], sig=sig)
                        notify_schyler(f"⚠️ ratewatch: '{h['name']}' re-capped on the SAME task right "
                                       f"after a resume (no progress) — backing off, not re-nudging. "
                                       f"The task may be too big for one usage window.")
                weekly = is_weekly(name)
                state = {"phase": "WEEKLY_HOLD" if (weekly and cfg["weekly_cap_escalate_only"]) else "CAPPED",
                         "binding": name, "pct": pct, "resets_at": resets_at,
                         "capped_at": int(now), "snapshot": snap, "resumes": {},
                         "last_window": state.get("last_window")}
                audit("capped", binding=name, pct=pct, resets_at=resets_at,
                      heads=[s["name"] for s in snap], weekly=weekly)
                if weekly and cfg["weekly_cap_escalate_only"]:
                    notify_schyler(f"🛑 ratewatch: WEEKLY usage cap hit (resets {resets_at}). Not "
                                   f"auto-sleeping for days — fleet HELD. {len(snap)} head(s) paused.")
                phase = state["phase"]

    if phase in ("CAPPED", "WEEKLY_HOLD"):
        secs = seconds_until(state.get("resets_at"), cfg["buffer_s"], now)
        if secs is None:
            audit("hold-bad-reset", resets_at=state.get("resets_at"))
            notify_schyler("⚠️ ratewatch: capped but resets_at is missing/unparseable — holding, "
                           "not resuming on bad data. Please check.")
        elif secs > 0:
            audit("waiting", binding=state.get("binding"), resuming_at=state.get("resets_at"),
                  seconds_left=secs)
        else:
            audit("resuming", binding=state.get("binding"), heads=[s.get("name") for s in state.get("snapshot") or []])
            state = _do_resume(state, cfg, drive, now, audit)
            phase = "WATCHING"

    _flush(audits, state, phase, now, drive, cfg)
    return 0


def _flush(audits: List[Dict[str, Any]], state: Dict[str, Any], phase: str, now: float,
           drive: bool, cfg: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> None:
    set_json(STATE_KEY, state)
    for entry in audits:
        rpush_capped(AUDIT_KEY, entry, AUDIT_MAX)
    status = {
        "generated_at": int(now),
        "mode": "live" if drive else "dry-run",
        "phase": phase,
        "binding": state.get("binding"),
        "resuming_at": state.get("resets_at"),
        "seconds_left": (seconds_until(state.get("resets_at"), cfg["buffer_s"], now)
                         if phase in ("CAPPED", "WEEKLY_HOLD") else None),
        "heads": [s.get("name") for s in state.get("snapshot") or []] if phase in ("CAPPED", "WEEKLY_HOLD") else [],
    }
    if extra:
        status.update(extra)
    set_json(STATUS_KEY, status, ttl_s=STATUS_TTL_S)
    if audits:
        log(f"cycle done — phase={phase} audits={len(audits)} mode={'LIVE' if drive else 'dry-run'}")


def main() -> int:
    drive = "--drive" in sys.argv[1:] or os.getenv("HQ_RATEWATCH_DRIVE") == "1"
    return run_cycle(drive)


if __name__ == "__main__":
    raise SystemExit(main())
