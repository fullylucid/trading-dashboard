#!/usr/bin/env python3
"""Hydra HQ fleet collector — 0-token host-side aggregator (DESIGN.md §4/§7).

The dashboard backend runs in Docker and CANNOT see host paths (~/.hydra-archives,
~/.claude, tmux) or run git/gh. So this script runs on the HOST every ~10s, reads the
local fleet state, builds one compact snapshot, and pushes it to the box Redis under key
``hq:fleet``. The backend (backend/hq_routes.py) is a thin read-only passthrough.

Security (DESIGN.md §8): transcripts/panes contain secrets that flashed by. We ship only
DERIVED, REDACTED status — the head's status enum, last-active time, and a scrubbed +
truncated copy of its last assistant *text* line. We NEVER ship raw transcript bodies,
tool inputs/outputs, or captured pane text to Redis/the browser.

Install:  cp scripts/hq_collector.py ~/.local/bin/hq-collector.py
Run:      python3 ~/.local/bin/hq-collector.py        (one shot; schedule via systemd timer/loop)

The pure helpers below (room_for, transcript_dir_name, redact, derive_status, …) take no
I/O and are unit-tested in backend/tests/test_hq_collector.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

HOME = os.path.expanduser("~")
REGISTRY = os.path.join(HOME, ".hydra-archives", ".registry")
ARCHIVES = os.path.join(HOME, ".hydra-archives")
PROJECTS = os.path.join(HOME, ".claude", "projects")
REDIS_CONTAINER = os.getenv("HQ_REDIS_CONTAINER", "tdbox-redis")
REDIS_KEY = "hq:fleet"
REDIS_TTL_S = 120  # snapshot is fresh for ~10s; TTL is a generous staleness backstop

# A head is "working" only if its transcript moved within this window; otherwise it's idle
# even while `claude` holds the pane. Tuned to the ~10s collector cadence + turn latency.
WORKING_WINDOW_S = 75
CURRENT_MAX_LEN = 160

# Known repos -> display name. Anything else falls back to a title-cased basename.
ROOM_NAMES = {
    "trading-dashboard": "Trading Dashboard",
    "cyborganic": "Cyborganic",
    "cribdar": "Cribdar",
    "employ": "Employ",
}

# ---------------------------------------------------------------------------- #
# Pure helpers (no I/O — unit tested)
# ---------------------------------------------------------------------------- #

def room_for(workdir: str) -> Tuple[str, str]:
    """Derive (room_id, room_name) from a head's working directory.

    Rooms are strictly per-repo (DESIGN locked decision). Hydra worktrees are named
    ``<repo>__<head>`` so the repo is the segment before ``__``; bare checkouts use their
    basename. Examples::

        /home/user/hydra-worktrees/trading-dashboard__hq   -> trading-dashboard
        /home/user/hydra-worktrees/cyborganic__data-gaia   -> cyborganic
        /home/user/cribdar                                 -> cribdar
        /home/user/Employ                                  -> Employ
    """
    base = os.path.basename(workdir.rstrip("/"))
    room_id = base.split("__", 1)[0] if "__" in base else base
    name = ROOM_NAMES.get(room_id.lower()) or room_id.replace("-", " ").title()
    return room_id, name


def transcript_dir_name(workdir: str) -> str:
    """Map a workdir to its ~/.claude/projects/<slug> directory name.

    Claude Code slugifies the absolute path by replacing every '/' and '_' with '-'
    (so a worktree's '__' becomes '--'). E.g. /home/user/hydra-worktrees/trading-dashboard__hq
    -> -home-user-hydra-worktrees-trading-dashboard--hq.
    """
    return workdir.rstrip("/").replace("/", "-").replace("_", "-")


# token/secret shapes we scrub from any string before it leaves the host
_SECRET_PATTERNS = [
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),         # OpenAI/Stripe-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),              # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),           # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}"),  # JWT
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),                       # long hex (api keys/hashes)
    re.compile(r"(?i)\b(token|secret|api[-_]?key|password|passwd|bearer)\b\s*[=:]\s*\S+"),
]


def redact(text: Optional[str]) -> str:
    """Scrub token-shaped substrings and truncate. Defense-in-depth: the current-line is
    already model-authored prose, but we never want a key that leaked into it to ship."""
    if not text:
        return ""
    s = " ".join(str(text).split())
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    if len(s) > CURRENT_MAX_LEN:
        s = s[: CURRENT_MAX_LEN - 1].rstrip() + "…"
    return s


def derive_status(
    pane_cmd: Optional[str],
    last_event_age_s: Optional[float],
    last_stop_reason: Optional[str],
    waiting: bool,
) -> str:
    """Collapse the raw signals into one of: working | idle | waiting-input | offline.

    - waiting-input: a permission/menu prompt is on the pane (detected host-side).
    - offline: no claude process holds the pane (it's at a shell / gone).
    - working: claude holds the pane AND the transcript moved recently AND the last turn
      didn't cleanly end (mid tool-use / still streaming).
    - idle: claude is up but quiet, or the last turn ended.
    """
    if pane_cmd is None or "claude" not in (pane_cmd or ""):
        return "offline"
    if waiting:
        return "waiting-input"
    recent = last_event_age_s is not None and last_event_age_s <= WORKING_WINDOW_S
    if recent and last_stop_reason not in ("end_turn", "stop_sequence"):
        return "working"
    return "idle"


# pane text that means Claude Code is blocked on the operator
_WAIT_MARKERS = (
    "do you want",
    "❯ 1.",
    "1. yes",
    "approve this",
    "allow this",
    "press enter to continue",
)


def pane_is_waiting(capture: Optional[str]) -> bool:
    """Heuristic: does the captured pane tail show a permission/confirmation prompt?
    Only the boolean leaves this host — never the captured text."""
    if not capture:
        return False
    low = capture.lower()
    return any(m in low for m in _WAIT_MARKERS)


def pane_is_rc_paired(capture: Optional[str]) -> bool:
    """Detect the 'Remote Control active' status line in a pane capture."""
    return bool(capture) and "remote control active" in capture.lower()


def parse_remote(url: str) -> Optional[str]:
    """Extract owner/repo from a git remote URL (ssh or https)."""
    if not url:
        return None
    u = url.strip().removesuffix(".git")
    m = re.search(r"[:/]([^/:]+/[^/:]+)$", u)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------- #
# I/O helpers
# ---------------------------------------------------------------------------- #

def _run(args: List[str], cwd: Optional[str] = None, timeout: float = 8.0) -> str:
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return out.stdout.strip()
    except Exception:
        return ""


def read_registry() -> List[Tuple[str, str]]:
    heads: List[Tuple[str, str]] = []
    try:
        with open(REGISTRY, "r") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or "\t" not in line:
                    continue
                name, workdir = line.split("\t", 1)
                if name and workdir:
                    heads.append((name.strip(), workdir.strip()))
    except FileNotFoundError:
        pass
    return heads


def tmux_panes() -> Dict[str, Dict[str, Any]]:
    """Map workdir -> {window, pane, cmd}. Keyed by pane_current_path (canonical)."""
    out = _run(
        ["tmux", "list-panes", "-a", "-F",
         "#{pane_current_path}\t#{window_index}\t#{pane_id}\t#{pane_current_command}"]
    )
    panes: Dict[str, Dict[str, Any]] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        path, win, pid, cmd = parts
        panes[path.rstrip("/")] = {"window": _int(win), "pane": pid, "cmd": cmd}
    return panes


def capture_pane(pane_id: str) -> str:
    return _run(["tmux", "capture-pane", "-p", "-t", pane_id], timeout=5.0)


def last_assistant(jsonl_path: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Read the tail of a transcript and return (redacted_text, last_ts_iso, stop_reason)
    of the most recent assistant turn. We only read the last slice of the file."""
    try:
        size = os.path.getsize(jsonl_path)
        with open(jsonl_path, "rb") as f:
            if size > 200_000:
                f.seek(size - 200_000)
                f.readline()  # discard partial line
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None, None, None

    text: Optional[str] = None
    ts: Optional[str] = None
    stop: Optional[str] = None
    for line in tail.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        msg = d.get("message") or {}
        if d.get("timestamp"):
            ts = d["timestamp"]
        if msg.get("stop_reason") is not None:
            stop = msg.get("stop_reason")
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    text = block["text"]
        elif isinstance(content, str) and content:
            text = content
    return (redact(text) if text else None), ts, stop


def latest_transcript(workdir: str) -> Optional[str]:
    d = os.path.join(PROJECTS, transcript_dir_name(workdir))
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda p: os.path.getmtime(p))


def git_info(workdir: str) -> Dict[str, Any]:
    branch = _run(["git", "-C", workdir, "rev-parse", "--abbrev-ref", "HEAD"]) or None
    porcelain = _run(["git", "-C", workdir, "status", "--porcelain"])
    uncommitted = len([x for x in porcelain.splitlines() if x.strip()]) if porcelain else 0
    ahead_s = _run(["git", "-C", workdir, "rev-list", "--count", "@{u}..HEAD"])
    if not ahead_s:  # no upstream — compare to origin/main
        ahead_s = _run(["git", "-C", workdir, "rev-list", "--count", "origin/main..HEAD"])
    last_commit = _run(["git", "-C", workdir, "log", "-1", "--format=%s"]) or None
    remote = parse_remote(_run(["git", "-C", workdir, "remote", "get-url", "origin"]))
    return {
        "branch": branch,
        "ahead": _int(ahead_s) or 0,
        "uncommitted": uncommitted,
        "last_commit": redact(last_commit) if last_commit else None,
        "remote": remote,
    }


def gh_open_prs(repo: str) -> List[Dict[str, Any]]:
    raw = _run(
        ["gh", "pr", "list", "--repo", repo, "--state", "open",
         "--json", "number,title,headRefName,mergeable", "-L", "30"],
        timeout=12.0,
    )
    try:
        items = json.loads(raw) if raw else []
    except ValueError:
        return []
    out = []
    for p in items:
        out.append({
            "number": p.get("number"),
            "title": redact(p.get("title")),
            "branch": p.get("headRefName"),
            "mergeable": p.get("mergeable") == "MERGEABLE",
        })
    return out


def _int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def _age(ts_iso: Optional[str], now: float) -> Optional[float]:
    if not ts_iso:
        return None
    try:
        t = ts_iso.replace("Z", "+00:00")
        from datetime import datetime
        return now - datetime.fromisoformat(t).timestamp()
    except Exception:
        return None


# ---------------------------------------------------------------------------- #
# Snapshot build
# ---------------------------------------------------------------------------- #

def build_snapshot() -> Dict[str, Any]:
    now = time.time()
    panes = tmux_panes()
    registry = read_registry()

    heads: List[Dict[str, Any]] = []
    rooms: Dict[str, Dict[str, Any]] = {}
    pr_cache: Dict[str, List[Dict[str, Any]]] = {}

    for name, workdir in registry:
        room_id, room_name = room_for(workdir)
        pane = panes.get(workdir.rstrip("/"))
        pane_cmd = pane["cmd"] if pane else None
        cap = capture_pane(pane["pane"]) if pane else None

        transcript = latest_transcript(workdir)
        current, last_ts, stop = (None, None, None)
        if transcript:
            current, last_ts, stop = last_assistant(transcript)
        age = _age(last_ts, now)
        status = derive_status(pane_cmd, age, stop, pane_is_waiting(cap))

        git = git_info(workdir)
        remote = git.pop("remote", None)

        # gather PRs per unique repo, cached
        if remote and remote not in pr_cache:
            pr_cache[remote] = gh_open_prs(remote)

        room = rooms.setdefault(room_id, {
            "id": room_id, "name": room_name, "repo": remote, "heads": [], "open_prs": [],
        })
        if remote and not room.get("repo"):
            room["repo"] = remote
        room["heads"].append(name)

        heads.append({
            "name": name,
            "room": room_id,
            "workdir": workdir,
            "branch": git["branch"],
            "status": status,
            "current": current,
            "last_active": last_ts,
            "last_active_age_s": round(age) if age is not None else None,
            "rc": {"paired": pane_is_rc_paired(cap), "name": name},
            "git": {
                "ahead": git["ahead"],
                "uncommitted": git["uncommitted"],
                "last_commit": git["last_commit"],
            },
            "tmux": {"window": pane["window"], "pane": pane["pane"]} if pane else None,
            "fossil_dir": os.path.join(ARCHIVES, name),
        })

    # attach PRs to rooms (match PR branch -> head where possible)
    branch_to_head = {h["branch"]: h["name"] for h in heads if h.get("branch")}
    for room in rooms.values():
        prs = pr_cache.get(room.get("repo") or "", [])
        for pr in prs:
            pr = dict(pr)
            pr["head"] = branch_to_head.get(pr.get("branch"))
            room["open_prs"].append(pr)

    return {
        "generated_at": int(now),
        "rooms": sorted(rooms.values(), key=lambda r: r["name"].lower()),
        "heads": sorted(heads, key=lambda h: (h["room"], h["name"].lower())),
        "activity": [],       # Slice 4
        "memory_index": [],   # Slice 3
    }


def push(snapshot: Dict[str, Any]) -> bool:
    payload = json.dumps(snapshot, separators=(",", ":"))
    try:
        p = subprocess.run(
            ["docker", "exec", "-i", REDIS_CONTAINER, "redis-cli", "-x", "SET", REDIS_KEY],
            input=payload, capture_output=True, text=True, timeout=10,
        )
        if p.returncode != 0:
            return False
        subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli", "EXPIRE", REDIS_KEY, str(REDIS_TTL_S)],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except Exception:
        return False


def main() -> int:
    snap = build_snapshot()
    ok = push(snap)
    if os.getenv("HQ_DEBUG"):
        print(json.dumps(snap, indent=2))
        print(f"[hq-collector] pushed={ok} heads={len(snap['heads'])} rooms={len(snap['rooms'])}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
