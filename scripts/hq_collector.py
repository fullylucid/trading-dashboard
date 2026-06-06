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
ROOMS_KEY = "hq:rooms"        # per-room detail (key docs) — kept out of hq:fleet to stay lean
MEMORY_KEY = "hq:memory"      # the git-tracked memory knowledge base (index + scrubbed bodies)
REDIS_TTL_S = 120  # snapshot is fresh for ~10s; TTL is a generous staleness backstop

# The canonical, git-tracked fleet memory (Charlotte's curated knowledge base). The per-project
# dirs (-home-user-<repo>/memory) are untracked scratch; this one is the [[link]]-graphed source.
MEMORY_DIR = os.getenv("HQ_MEMORY_DIR", os.path.join(PROJECTS, "-home-user", "memory"))
MEMORY_MAX_BYTES = 60_000
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+?)(?:\|[^\]]+)?\]\]")

# Per-room "key docs" to surface in the room view. First match per (key,label) wins, scanned
# in the room's MAIN checkout. Repos differ (blueprint vs design; roadmap naming), so each
# category lists ordered candidates relative to the repo root.
DOC_CANDIDATES = [
    ("readme", "README", ["README.md", "readme.md"]),
    ("blueprint", "Blueprint", ["docs/BLUEPRINT.md", "BLUEPRINT.md", "docs/DESIGN.md", "DESIGN.md"]),
    ("roadmap", "Roadmap", ["docs/ROADMAP.md", "ROADMAP.md", "docs/roadmap.md"]),
    ("architecture", "Architecture", ["docs/architecture.md", "ARCHITECTURE.md", "SYSTEM_ARCHITECTURE.md", "docs/ARCHITECTURE.md"]),
]
DOC_MAX_BYTES = 80_000  # cap any single doc we ship (very large READMEs get truncated)

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


def scrub_secrets(text: Optional[str]) -> str:
    """Replace token-shaped substrings with [REDACTED]; preserve structure/whitespace.
    Used for doc bodies (which keep their markdown layout)."""
    if not text:
        return ""
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def redact(text: Optional[str]) -> str:
    """Scrub token-shaped substrings, collapse whitespace, and truncate. For one-line status
    summaries (current task, commit subject). Defense-in-depth: these are model/author prose,
    but we never want a key that leaked into them to ship."""
    if not text:
        return ""
    s = " ".join(scrub_secrets(text).split())
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


def pick_room_workdir(workdirs: List[str]) -> Optional[str]:
    """Choose the checkout to read a room's key docs from. Prefer a MAIN checkout (basename
    has no '__', i.e. not a feature worktree on a possibly-stale branch); else the first."""
    if not workdirs:
        return None
    for wd in workdirs:
        if "__" not in os.path.basename(wd.rstrip("/")):
            return wd
    return workdirs[0]


def parse_remote(url: str) -> Optional[str]:
    """Extract owner/repo from a git remote URL (ssh or https)."""
    if not url:
        return None
    u = url.strip().removesuffix(".git")
    m = re.search(r"[:/]([^/:]+/[^/:]+)$", u)
    return m.group(1) if m else None


def split_frontmatter(text: str) -> Tuple[str, str]:
    """Split a markdown doc into (frontmatter_block, body). Frontmatter is a leading
    ``---`` … ``---`` fence; returns ("", text) when there isn't one."""
    if not text.startswith("---"):
        return "", text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]).lstrip("\n")
    return "", text


def parse_frontmatter(text: str) -> Dict[str, Any]:
    """Tiny YAML-subset parser for memory frontmatter — flat ``key: value`` plus a one-level
    nested ``metadata:`` block. No yaml dependency; values are kept as strings (quotes stripped).
    Good enough for our hand-written frontmatter; unknown shapes are ignored, never raised."""
    fm, _ = split_frontmatter(text)
    out: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    in_meta = False
    for raw in fm.split("\n"):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[0] in (" ", "\t")
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "metadata" and not val:
            in_meta = True
            continue
        if in_meta and indented:
            meta[key] = val
        else:
            in_meta = False
            out[key] = val
    if meta:
        out["metadata"] = meta
    return out


def extract_wikilinks(text: str) -> List[str]:
    """Return the ordered, de-duplicated ``[[target]]`` names in a body (``[[a|alias]]`` → ``a``)."""
    seen: List[str] = []
    for m in _WIKILINK_RE.finditer(text or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


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


def collect_room_docs(workdir: str) -> List[Dict[str, Any]]:
    """Scan a room's main checkout for its key docs (README/blueprint/roadmap/architecture).
    Returns [{key,label,path,markdown}] for each category's first existing candidate. Docs are
    git-tracked + trusted, but we still secret-scrub and cap size before they leave the host."""
    docs: List[Dict[str, Any]] = []
    for key, label, candidates in DOC_CANDIDATES:
        for rel in candidates:
            full = os.path.join(workdir, rel)
            if not os.path.isfile(full):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    body = f.read(DOC_MAX_BYTES + 1)
            except OSError:
                break
            truncated = len(body) > DOC_MAX_BYTES
            if truncated:
                body = body[:DOC_MAX_BYTES].rstrip() + "\n\n…(truncated)"
            docs.append({
                "key": key,
                "label": label,
                "path": rel,
                "markdown": scrub_secrets(body),
                "truncated": truncated,
            })
            break
    return docs


def collect_memory() -> Dict[str, Any]:
    """Read the git-tracked memory dir into an index + per-doc bodies for the HQ memory browser.

    For each ``memory/*.md`` (skipping the MEMORY.md/README.md meta files): parse frontmatter,
    strip it from the body, secret-scrub + cap the body, and extract outbound ``[[wikilinks]]``.
    Backlinks are computed by inverting the link graph (only over targets that exist). Returns
    {"index": [...summary...], "docs": {name: {...full...}}}.
    """
    docs: Dict[str, Dict[str, Any]] = {}
    try:
        names = sorted(n for n in os.listdir(MEMORY_DIR) if n.endswith(".md"))
    except OSError:
        return {"index": [], "docs": {}}

    for fname in names:
        if fname in ("MEMORY.md", "README.md"):
            continue
        name = fname[:-3]  # strip .md — this is the [[wikilink]] target
        try:
            with open(os.path.join(MEMORY_DIR, fname), "r", encoding="utf-8", errors="replace") as f:
                text = f.read(MEMORY_MAX_BYTES + 1)
        except OSError:
            continue
        truncated = len(text) > MEMORY_MAX_BYTES
        if truncated:
            text = text[:MEMORY_MAX_BYTES]
        fm = parse_frontmatter(text)
        _, body = split_frontmatter(text)
        meta = fm.get("metadata", {}) if isinstance(fm.get("metadata"), dict) else {}
        docs[name] = {
            "name": name,
            "title": fm.get("name") or name,
            "description": fm.get("description", ""),
            "type": meta.get("type", "note"),
            "scope": meta.get("scope"),
            "updated": meta.get("updated") or meta.get("created"),
            "confidence": meta.get("confidence"),
            "links_out": extract_wikilinks(body),
            "body": scrub_secrets(body) + ("\n\n…(truncated)" if truncated else ""),
        }

    # backlinks: invert links_out, but only over targets that actually exist
    existing = set(docs)
    for name, d in docs.items():
        d["links_out"] = [l for l in d["links_out"]]  # keep raw (broken ones flagged client-side)
        d["links_in"] = sorted(
            other for other, od in docs.items()
            if name in od["links_out"] and other != name
        )

    index = sorted(
        ({
            "name": d["name"], "title": d["title"], "description": d["description"],
            "type": d["type"], "scope": d["scope"], "updated": d["updated"],
            "n_links": len([l for l in d["links_out"] if l in existing]) + len(d["links_in"]),
        } for d in docs.values()),
        key=lambda x: (x["type"], x["name"]),
    )
    return {"index": index, "docs": docs}


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
    room_workdirs: Dict[str, List[str]] = {}

    for name, workdir in registry:
        room_id, room_name = room_for(workdir)
        room_workdirs.setdefault(room_id, []).append(workdir)
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

    memory = collect_memory()

    fleet = {
        "generated_at": int(now),
        "rooms": sorted(rooms.values(), key=lambda r: r["name"].lower()),
        "heads": sorted(heads, key=lambda h: (h["room"], h["name"].lower())),
        "activity": [],                       # Slice 4
        "memory_index": memory["index"],      # lightweight index (full bodies in hq:memory)
    }

    # Per-room detail: key docs from each room's main checkout (served by /api/hq/room/{id}).
    rooms_detail = {
        "generated_at": int(now),
        "rooms": {
            rid: {"docs": collect_room_docs(pick_room_workdir(wds) or wds[0])}
            for rid, wds in room_workdirs.items()
        },
    }
    memory_payload = {"generated_at": int(now), **memory}
    return {"fleet": fleet, "rooms_detail": rooms_detail, "memory": memory_payload}


def push_key(key: str, payload: Dict[str, Any]) -> bool:
    blob = json.dumps(payload, separators=(",", ":"))
    try:
        p = subprocess.run(
            ["docker", "exec", "-i", REDIS_CONTAINER, "redis-cli", "-x", "SET", key],
            input=blob, capture_output=True, text=True, timeout=10,
        )
        if p.returncode != 0:
            return False
        subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli", "EXPIRE", key, str(REDIS_TTL_S)],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except Exception:
        return False


def main() -> int:
    out = build_snapshot()
    fleet, rooms_detail, memory = out["fleet"], out["rooms_detail"], out["memory"]
    ok = push_key(REDIS_KEY, fleet)
    ok_rooms = push_key(ROOMS_KEY, rooms_detail)
    ok_mem = push_key(MEMORY_KEY, memory)
    if os.getenv("HQ_DEBUG"):
        print(json.dumps(fleet, indent=2))
        ndocs = sum(len(r["docs"]) for r in rooms_detail["rooms"].values())
        print(f"[hq-collector] fleet={ok} rooms={ok_rooms} memory={ok_mem} "
              f"heads={len(fleet['heads'])} rooms={len(fleet['rooms'])} docs={ndocs} "
              f"mem={len(memory['index'])}")
    return 0 if (ok and ok_rooms and ok_mem) else 1


if __name__ == "__main__":
    raise SystemExit(main())
