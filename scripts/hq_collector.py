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
HEADS_KEY = "hq:heads"        # per-head detail (recent commits, fossil index, memory scope)
COMMANDS_KEY = "hq:commands"  # slash-command catalog for the console autocomplete
ROADMAP_KEY = "hq:roadmap"    # per-room living roadmap (nested checklist ∪ PR state)
REDIS_TTL_S = 120  # snapshot is fresh for ~10s; TTL is a generous staleness backstop

# Living-roadmap source files per room (main checkout). Override per room in rooms.config.json
# via "roadmaps": {room_id: relpath}. Convention: nested markdown checklist (headings = epics,
# indented `- [ ]`/`- [x]` = tasks/subtasks) + `@owner` tags + `{milestone:NAME}` markers.
ROADMAP_CANDIDATES = ["ROADMAP.md", "CHECKLIST.md", ".hq/roadmap.md", "docs/ROADMAP.md"]
_OWNER_RE = re.compile(r"@([A-Za-z0-9][\w-]*)")
_MILESTONE_RE = re.compile(r"\{milestone:\s*([^}]+)\}", re.IGNORECASE)
_PRNUM_RE = re.compile(r"#(\d{1,6})\b")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_ITEM_RE = re.compile(r"^(\s*)[-*+]\s+(?:\[([ xX])\]\s+)?(.*)$")
_STOPWORDS = {"the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with", "via", "add",
              "fix", "feat", "use", "from", "into", "that", "this", "its"}

# Slash-command catalog (console autocomplete). Three sources: curated built-ins, user-invocable
# skills (~/.claude/skills/*/SKILL.md frontmatter), and custom commands (.claude/commands/*.md).
# The collector enumerates + publishes to Redis (hq:commands) so the container needn't mount more
# of ~/.claude. Names are stored WITHOUT the leading slash; the UI adds it.
SKILLS_DIR = os.getenv("HQ_SKILLS_DIR", os.path.join(HOME, ".claude", "skills"))
COMMANDS_DIRS = [
    os.path.join(HOME, ".claude", "commands"),                 # user-global custom commands
    os.path.join(HOME, "trading-dashboard", ".claude", "commands"),  # project custom commands
]
BUILTIN_COMMANDS = [
    ("help", "Show help and the list of commands"),
    ("clear", "Clear the conversation history"),
    ("compact", "Summarize + compact the conversation to free up context"),
    ("model", "Switch the active model"),
    ("effort", "Set reasoning effort (low / medium / high / max)"),
    ("cost", "Show token usage + cost for this session"),
    ("memory", "View / edit CLAUDE.md memory"),
    ("agents", "Manage subagents"),
    ("resume", "Resume a previous conversation"),
    ("remote-control", "Connect Remote Control to drive this session"),
    ("review", "Review a pull request"),
    ("init", "Initialize a CLAUDE.md for the codebase"),
    ("vim", "Toggle vim editing mode in the composer"),
    ("config", "Open Claude Code settings"),
    ("color", "Change the theme"),
]

# Category layer (roadmap A2): a grouping ABOVE the per-repo rooms, so the conductor + hq head
# get their own "Command" group instead of being mis-filed under the trading-dashboard product
# room. Customizable via rooms.config.json in the HYDRA-HQ repo (HQ owns its own org chart);
# this baked-in default applies when the file is absent. Each custom category claims heads by
# `roles` and/or explicit `heads`; everything else falls back to its room.
ROOMS_CONFIG_PATH = os.getenv("HQ_ROOMS_CONFIG", os.path.join(HOME, "hydra-hq", "rooms.config.json"))
# External heads (B1): agents not visible to WSL tmux/registry (e.g. win-gaia on Windows) that
# report liveness via a file-message bus heartbeat. The collector reads each heartbeat file and
# its mtime; new external agents are added by CONFIG, not code.
EXTERNAL_STALE_S = 45 * 60   # heartbeat older than this (gaia polls ~20-25min) -> dormant
DEFAULT_ROOMS_CONFIG: Dict[str, Any] = {
    "categories": [
        {"id": "command", "label": "🛰️ Command", "roles": ["conductor", "hq"], "heads": []},
    ],
    "order": ["command"],     # category ids first, in this order; remaining rooms follow (alpha)
    "room_labels": {},        # optional per-room display-label overrides
    "external_heads": [       # bus/heartbeat-reported heads (no tmux/git) — see collect_external_heads
        {"name": "win-gaia", "heartbeat_path": "/mnt/c/cyborganic-bus/heartbeat-win.md",
         "room": "cyborganic", "kind": "windows"},
    ],
}

# Per-head detail sizing. Fossils are large transcripts — we ship only an INDEX (names/mtime/
# size, NEVER bodies; DESIGN §8). Live fossil full-text search needs a host request path we
# don't have (collector is push-only) — a Phase-2 follow-up.
HEAD_COMMITS = 12
HEAD_FOSSILS_MAX = 40

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

# Fleet activity feed: PR opened/merged events + each head's commits ahead of origin/main,
# within this lookback, newest-first, capped.
ACTIVITY_WINDOW_S = 72 * 3600
ACTIVITY_MAX = 60
ACTIVITY_COMMITS_PER_HEAD = 10

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


def role_for(name: str, workdir: str) -> str:
    """Classify a head as conductor | hq | head — a derivable signal for the Command-category
    layer (roadmap A2), so the conductor (charlotte) and the hq head can be grouped out of the
    trading-dashboard *product* room without hardcoding the org chart here.

    - conductor: runs from the home dir (not a repo worktree), i.e. Charlotte. ``charlotte``
      name is a fallback signal.
    - hq: the hq head — name ``hq`` or a ``*__hq`` worktree.
    - head: everything else (a normal project head).
    """
    wd = workdir.rstrip("/")
    if wd == HOME or name == "charlotte":
        return "conductor"
    if name == "hq" or os.path.basename(wd).split("__")[-1] == "hq":
        return "hq"
    return "head"


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


# A menu option line in the Claude Code TUI: an optional ❯ cursor, ≤3 leading spaces, then
# "N. label". Descriptions wrap at ~5 spaces with NO leading number, so they don't match —
# that's how we keep option lines and skip their blurbs. (Permission renders "2.Yes"; menus
# render "2. label" — the space after the dot is optional.)
_OPT_RE = re.compile(r"^[ \t]{0,3}❯?[ \t]?(\d{1,2})\.[ \t]?(\S.*)$")
_MENU_SIG = ("enter to select", "arrow keys to navigate", "tab/arrow")


def parse_prompt(capture: Optional[str]) -> Optional[Dict[str, Any]]:
    """When a head is blocked on a menu, lift the question + its options off the pane so the
    console can render tappable buttons (F6). Two shapes, distinguished by their footer:

    - ``permission`` — "Do you want to proceed?" + numbered Yes/No. Answered number+Enter.
    - ``question``   — an AskUserQuestion menu ("Enter to select · Tab/Arrow keys to navigate").
      Answered by arrow-nav + Enter (cursor starts at option 1, as the TUI renders it).

    This is the ONE place pane-derived prose leaves the host — and only because the menu IS
    what the operator is being asked to answer. Every field is secret-scrubbed via ``redact``
    (defense-in-depth: a command echoed into an option shouldn't ship a leaked token)."""
    if not capture:
        return None
    low = capture.lower()
    is_permission = "do you want to proceed" in low
    is_menu = any(s in low for s in _MENU_SIG)
    if not (is_permission or is_menu):
        return None

    lines = capture.split("\n")
    options: List[Dict[str, Any]] = []
    first_opt = None
    for i, ln in enumerate(lines):
        m = _OPT_RE.match(ln)
        if not m:
            continue
        idx = int(m.group(1))
        if any(o["index"] == idx for o in options):  # ignore wrapped/duplicate echoes
            continue
        # permission option labels often trail "  : <command echo>" — drop that noise
        label = m.group(2).split("  :", 1)[0].strip()
        options.append({"index": idx, "label": redact(label)})
        if first_opt is None:
            first_opt = i
    # must be a real 1..N menu (guards against a stray "3. foo" in scrollback)
    if len(options) < 2 or options[0]["index"] != 1:
        return None

    question = ""
    for j in range(first_opt - 1, -1, -1):
        t = lines[j].strip()
        if not t or set(t) <= set("─-—=•· "):  # blank / box-rule / dots
            continue
        if "✔" in t or t.startswith("←") or t.endswith("→"):  # multiselect tab bar
            continue
        question = redact(t)
        break

    return {
        "kind": "permission" if is_permission else "question",
        "nav": "number" if is_permission else "arrow",
        "question": question or ("Do you want to proceed?" if is_permission else ""),
        "options": options,
    }


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
    """Map workdir -> {window, name, session, pane, cmd}. Keyed by pane_current_path
    (canonical). On a workdir collision (e.g. a shell window + the head's claude window in
    the same dir), a pane running `claude` wins — that's the head's live pane."""
    out = _run(
        ["tmux", "list-panes", "-a", "-F",
         "#{pane_current_path}\t#{window_index}\t#{window_name}\t#{session_name}\t#{pane_id}\t#{pane_current_command}"]
    )
    panes: Dict[str, Dict[str, Any]] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        path, win, wname, session, pid, cmd = parts
        key = path.rstrip("/")
        prev = panes.get(key)
        # keep a claude pane over a non-claude one for the same dir
        if prev is not None and "claude" in (prev.get("cmd") or "") and "claude" not in cmd:
            continue
        panes[key] = {"window": _int(win), "name": wname, "session": session, "pane": pid, "cmd": cmd}
    return panes


def discover_heads(
    registry: List[Tuple[str, str]], panes: Dict[str, Dict[str, Any]]
) -> List[Tuple[str, str]]:
    """The fleet roster = the registry UNIONed with live tmux discovery, so HQ reflects
    reality instead of a stale ~/.hydra-archives/.registry (which drifts when heads spawn
    without registering). Every pane in the 'hydra' session running `claude` is treated as a
    head (name = window name, workdir = pane path, room derived from the workdir). De-duped by
    workdir; the registry entry wins the name when both have the same dir, and registered heads
    not currently in tmux are still kept (supplement, not replacement).

    Cross-OS gap (out of scope): heads running on the Windows side (e.g. win-gaia) aren't in
    WSL tmux OR the registry, so neither source sees them — that needs a Windows-side reporter
    or a static external-roster file the collector merges. Tracked as a follow-up.
    """
    heads: List[Tuple[str, str]] = []
    seen: set = set()
    for name, workdir in registry:
        key = workdir.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        heads.append((name, workdir))
    for workdir, p in panes.items():
        if p.get("session") != "hydra" or "claude" not in (p.get("cmd") or ""):
            continue
        key = workdir.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        heads.append((p.get("name") or os.path.basename(key), workdir))
    return heads


def load_rooms_config() -> Dict[str, Any]:
    """Load the category config from the hydra-hq repo, falling back to the baked-in default.
    A present file is shallow-merged over the default (its keys win), so a partial file still
    gets sane defaults. Never raises — a broken/missing file just yields the default."""
    cfg = dict(DEFAULT_ROOMS_CONFIG)
    try:
        with open(ROOMS_CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if v is not None})
    except (OSError, ValueError):
        pass
    return cfg


def assign_categories(
    heads: List[Dict[str, Any]], room_names: Dict[str, str], config: Dict[str, Any]
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Group heads into ordered categories ABOVE the per-repo rooms (roadmap A2). Pure.

    A head joins the first custom category that lists its name in ``heads`` or its role in
    ``roles``; otherwise it stays in its room (a room-category). Returns
    ``(category_by_head, ordered_categories)`` where each category is
    ``{id, label, kind: 'custom'|'room', room?, heads: [names]}``. With no custom categories
    this collapses to exactly the rooms, so behaviour is unchanged when the config is empty.
    """
    customs = config.get("categories") or []
    cat_by_head: Dict[str, str] = {}
    members: Dict[str, List[str]] = {}
    labels: Dict[str, str] = {}
    kinds: Dict[str, str] = {}

    def claims(cat: Dict[str, Any], head: Dict[str, Any]) -> bool:
        return head["name"] in (cat.get("heads") or []) or head.get("role") in (cat.get("roles") or [])

    for head in heads:
        cid = head.get("room")
        for cat in customs:
            if claims(cat, head):
                cid = cat["id"]
                labels[cid] = cat.get("label", cid)
                kinds[cid] = "custom"
                break
        cat_by_head[head["name"]] = cid
        members.setdefault(cid, []).append(head["name"])

    # room-categories get their room display name (or a config label override)
    room_labels = config.get("room_labels") or {}
    for cid in members:
        if cid not in kinds:
            kinds[cid] = "room"
            labels[cid] = room_labels.get(cid) or room_names.get(cid, cid)

    # order: configured ids first (in order), then remaining rooms alpha by label
    order = config.get("order") or []
    ordered_ids = [cid for cid in order if cid in members]
    rest = sorted((cid for cid in members if cid not in ordered_ids), key=lambda c: labels[c].lower())
    categories = [
        {
            "id": cid, "label": labels[cid], "kind": kinds[cid],
            **({"room": cid} if kinds[cid] == "room" else {}),
            "heads": members[cid],
        }
        for cid in ordered_ids + rest
    ]
    return cat_by_head, categories


def parse_heartbeat(text: str) -> Dict[str, Any]:
    """Parse a gaia-bus heartbeat line 'tick N · <status> · <date>' (see BUS.md). The status
    can itself contain ' · ', so only the first (tick) and last (date) fields are split off."""
    parts = [p.strip() for p in (text or "").strip().split(" · ")]
    tick = None
    if parts and parts[0].lower().startswith("tick"):
        m = re.search(r"\d+", parts[0])
        tick = int(m.group()) if m else None
        parts = parts[1:]
    date = parts.pop() if len(parts) >= 2 else None
    status = " · ".join(parts).strip()
    return {"tick": tick, "status": status, "date": date}


def external_status(age_s: Optional[float], stale_after_s: int = EXTERNAL_STALE_S) -> str:
    """Liveness for a heartbeat head: idle while fresh, dormant once the tick stops advancing
    (BUS.md: 'if a heartbeat hasn't advanced in a while, assume its loop is paused → surface').
    `None` age means no heartbeat file at all -> offline."""
    if age_s is None:
        return "offline"
    return "idle" if age_s <= stale_after_s else "dormant"


def collect_external_heads(config: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
    """Build head records for config-declared external agents from their bus heartbeat files.
    No git/tmux/fossils — just status + tick + last-heartbeat, derived from the file's content
    and mtime. Status text is secret-scrubbed + truncated like any status line."""
    heads: List[Dict[str, Any]] = []
    for ext in config.get("external_heads") or []:
        name = ext.get("name")
        path = ext.get("heartbeat_path")
        if not name or not path:
            continue
        room_id = ext.get("room") or room_for(path)[0]
        stale_after = ext.get("stale_after_s", EXTERNAL_STALE_S)
        tick, current, last_iso, age = None, None, None, None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                hb = parse_heartbeat(f.read(8000))
            mtime = os.path.getmtime(path)
            age = now - mtime
            last_iso = _epoch_to_iso(mtime)
            tick = hb["tick"]
            current = redact(hb["status"]) or None
        except OSError:
            pass
        status = external_status(age, stale_after)
        heads.append({
            "name": name,
            "room": room_id,
            "role": "head",
            "workdir": None,
            "branch": None,
            "status": status,
            "current": current,
            "last_active": last_iso,
            "last_active_age_s": round(age) if age is not None else None,
            "source": "bus",
            "kind": ext.get("kind", "external"),
            "tick": tick,
            "rc": {"paired": False, "name": name},
            "git": {"ahead": 0, "uncommitted": 0, "last_commit": None},
            "tmux": None,
            "fossil_dir": None,
        })
    return heads


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


def gh_repo_prs(repo: str) -> List[Dict[str, Any]]:
    """One gh call per repo: the most-recently-updated PRs across all states. Feeds BOTH the
    room open-PR list and the activity feed's opened/merged events (these repos have few PRs,
    so the recent slice reliably includes every currently-open one)."""
    raw = _run(
        ["gh", "pr", "list", "--repo", repo, "--state", "all", "--search", "sort:updated-desc",
         "--json", "number,title,state,headRefName,mergeable,createdAt,mergedAt", "-L", "40"],
        timeout=12.0,
    )
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def open_prs_from(prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Room open-PR shape from the raw gh list (state == OPEN)."""
    return [
        {
            "number": p.get("number"),
            "title": redact(p.get("title")),
            "branch": p.get("headRefName"),
            "mergeable": p.get("mergeable") == "MERGEABLE",
        }
        for p in prs if p.get("state") == "OPEN"
    ]


def pr_events_from(
    prs: List[Dict[str, Any]], repo: str, room_id: str,
    branch_to_head: Dict[str, str], since_ts: float,
) -> List[Dict[str, Any]]:
    """Activity events for PRs opened/merged within the window. A PR can emit both."""
    events: List[Dict[str, Any]] = []
    for p in prs:
        num = p.get("number")
        head = branch_to_head.get(p.get("headRefName"))
        base = {
            "room": room_id, "head": head, "number": num,
            "text": redact(p.get("title")),
            "url": f"https://github.com/{repo}/pull/{num}" if num else None,
        }
        opened = _iso_to_epoch(p.get("createdAt"))
        if opened is not None and opened >= since_ts:
            events.append({**base, "ts": opened, "kind": "pr_opened"})
        merged = _iso_to_epoch(p.get("mergedAt"))
        if merged is not None and merged >= since_ts:
            events.append({**base, "ts": merged, "kind": "pr_merged"})
    return events


def head_commit_events(workdir: str, head: str, room_id: str, since_ts: float) -> List[Dict[str, Any]]:
    """A head's own commits ahead of origin/main, within the window — its in-progress work.
    Branch-scoped, so low duplication across heads. Commit subjects are secret-scrubbed."""
    out = _run([
        "git", "-C", workdir, "log", "origin/main..HEAD",
        f"--since=@{int(since_ts)}", f"-n{ACTIVITY_COMMITS_PER_HEAD}",
        "--no-merges", "--format=%H%x00%ct%x00%s",
    ])
    events: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\x00")
        if len(parts) != 3:
            continue
        sha, ct, subj = parts
        events.append({
            "ts": _int(ct), "kind": "commit", "head": head, "room": room_id,
            "sha": sha[:9], "text": redact(subj),
        })
    return events


def finalize_activity(items: List[Dict[str, Any]], cap: int = ACTIVITY_MAX) -> List[Dict[str, Any]]:
    """De-dup (by kind+number for PRs, kind+sha for commits), sort newest-first, cap."""
    seen = set()
    uniq = []
    for it in items:
        if it.get("ts") is None:
            continue
        key = (it["kind"], it.get("number"), it.get("sha"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    uniq.sort(key=lambda x: x["ts"], reverse=True)
    return uniq[:cap]


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


def head_recent_commits(workdir: str) -> List[Dict[str, Any]]:
    """Recent commits on the head's current branch (HEAD), scrubbed. For the per-head detail
    view's history panel — unlike the activity feed's ahead-of-main slice, this is plain history."""
    out = _run([
        "git", "-C", workdir, "log", f"-n{HEAD_COMMITS}", "--no-merges",
        "--format=%H%x00%ct%x00%s",
    ])
    commits: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\x00")
        if len(parts) != 3:
            continue
        sha, ct, subj = parts
        commits.append({"sha": sha[:9], "ts": _int(ct), "text": redact(subj)})
    return commits


def head_fossils(head: str) -> Dict[str, Any]:
    """Index the head's archived transcripts under ~/.hydra-archives/<head>/ — file names,
    mtimes, sizes, and a session/subagent classification. NO bodies leave the host (DESIGN §8);
    fossils hold raw transcripts with secrets, so we ship only this metadata index."""
    root = os.path.join(ARCHIVES, head)
    entries: List[Dict[str, Any]] = []
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            total += 1
            full = os.path.join(dirpath, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            entries.append({
                "name": fn,
                "ts": int(st.st_mtime),
                "size": st.st_size,
                "kind": "subagent" if "subagents" in dirpath else "session",
            })
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return {"count": total, "files": entries[:HEAD_FOSSILS_MAX]}


def _first_prose_line(body: str) -> str:
    for ln in body.splitlines():
        s = ln.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return s
    return ""


def collect_commands() -> Dict[str, Any]:
    """Enumerate the slash-command catalog: curated built-ins + user-invocable skills + custom
    commands. Each entry is {name, desc, source}; name has no leading slash. Only the frontmatter
    (first ~1KB) of each SKILL.md is read, so 149 skills stay cheap to scan."""
    cmds: List[Dict[str, Any]] = []

    for name, desc in BUILTIN_COMMANDS:
        cmds.append({"name": name, "desc": desc, "source": "builtin"})

    # skills — name + description from SKILL.md frontmatter
    skills: List[Dict[str, Any]] = []
    try:
        for entry in sorted(os.listdir(SKILLS_DIR)):
            sp = os.path.join(SKILLS_DIR, entry, "SKILL.md")
            if not os.path.isfile(sp):
                continue
            try:
                with open(sp, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(2048)
            except OSError:
                continue
            fm = parse_frontmatter(head)
            sname = (fm.get("name") or entry).strip()
            sdesc = redact(fm.get("description", "")) or ""
            if sname:
                skills.append({"name": sname, "desc": sdesc, "source": "skill"})
    except OSError:
        pass
    skills.sort(key=lambda c: c["name"].lower())
    cmds.extend(skills)

    # custom commands — <dir>/*.md -> /<filename>
    custom: List[Dict[str, Any]] = []
    seen_custom = set()
    for d in COMMANDS_DIRS:
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".md"))
        except OSError:
            continue
        for fn in names:
            cname = fn[:-3]
            if cname in seen_custom:
                continue
            seen_custom.add(cname)
            try:
                with open(os.path.join(d, fn), "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(2048)
            except OSError:
                continue
            fm = parse_frontmatter(text)
            _, body = split_frontmatter(text)
            cdesc = redact(fm.get("description") or _first_prose_line(body))
            custom.append({"name": cname, "desc": cdesc, "source": "custom"})
    cmds.extend(custom)

    return {"commands": cmds, "counts": {
        "builtin": len(BUILTIN_COMMANDS), "skill": len(skills), "custom": len(custom)}}


# ---------------------------------------------------------------------------- living roadmap
def _extract_tags(text: str) -> Tuple[str, Optional[str], Optional[str], Optional[int]]:
    """Pull @owner, {milestone:NAME}, and a #PR ref out of an item's text; return the cleaned
    text plus (owner, milestone, pr_ref)."""
    owner = None
    mo = _OWNER_RE.search(text)
    if mo:
        owner = mo.group(1)
    ms = _MILESTONE_RE.search(text)
    milestone = ms.group(1).strip() if ms else None
    pr = _PRNUM_RE.search(text)
    pr_ref = int(pr.group(1)) if pr else None
    clean = _MILESTONE_RE.sub("", text)
    clean = _OWNER_RE.sub("", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip(" -·•\t")
    return clean, owner, milestone, pr_ref


def parse_roadmap(text: str) -> List[Dict[str, Any]]:
    """Parse a nested markdown checklist into a tree. Markdown headings (``##``..) are epic/group
    nodes; ``- [ ]``/``- [x]`` (and plain bullets) nest by heading + indentation. Each node carries
    owner / milestone / checked + children. Pure."""
    root: Dict[str, Any] = {"depth": -1, "children": []}
    stack: List[Dict[str, Any]] = [root]

    def attach(node: Dict[str, Any], depth: int) -> None:
        while stack and stack[-1]["depth"] >= depth:
            stack.pop()
        stack[-1]["children"].append(node)
        node["depth"] = depth
        stack.append(node)

    for raw in text.split("\n"):
        # a line that is ONLY a {milestone:NAME} marker -> a divider node (epic-level)
        if _MILESTONE_RE.search(raw) and not _HEADING_RE.match(raw) and not _ITEM_RE.match(raw):
            if not _MILESTONE_RE.sub("", raw).strip():
                attach({"text": "", "checked": None, "owner": None,
                        "milestone": _MILESTONE_RE.search(raw).group(1).strip(), "children": []}, depth=2)
                continue
        h = _HEADING_RE.match(raw)
        if h:
            clean, owner, milestone, _ = _extract_tags(h.group(2))
            if not clean and not milestone:
                continue
            attach({"text": clean, "checked": None, "owner": owner, "milestone": milestone,
                    "children": []}, depth=len(h.group(1)))
            continue
        m = _ITEM_RE.match(raw)
        if m:
            indent = len(m.group(1).replace("\t", "  "))
            checked = None if m.group(2) is None else m.group(2).lower() == "x"
            clean, owner, milestone, pr_ref = _extract_tags(m.group(3))
            if not clean and not milestone:
                continue
            attach({"text": clean, "checked": checked, "owner": owner, "milestone": milestone,
                    "pr_ref": pr_ref, "children": []}, depth=100 + indent // 2)
    return root["children"]


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) >= 4 and w not in _STOPWORDS}


def match_pr(text: str, pr_ref: Optional[int], prs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cross-reference a checklist item to a PR — by explicit ``#num`` first, else a conservative
    word-overlap on the title. Returns {number,url,state,title} or None."""
    by_num = {p.get("number"): p for p in prs}
    if pr_ref and pr_ref in by_num:
        p = by_num[pr_ref]
        return {"number": p["number"], "url": p.get("url"), "state": p.get("state"), "title": p.get("title")}
    iw = _words(text)
    if len(iw) < 2:
        return None
    best, best_score = None, 0.0
    for p in prs:
        tw = _words(p.get("title", ""))
        if not tw:
            continue
        score = len(iw & tw) / len(iw)
        if score > best_score:
            best, best_score = p, score
    if best and best_score >= 0.6:
        return {"number": best["number"], "url": best.get("url"), "state": best.get("state"), "title": best.get("title")}
    return None


def fuse_roadmap(nodes: List[Dict[str, Any]], prs: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Annotate each leaf checklist item with status (done | in_progress | planned) + its matched
    PR, in place. A ``[x]`` item or one matching a MERGED PR is done; an OPEN PR -> in_progress.
    Returns (done, total) leaf counts for the progress meter."""
    done = total = 0
    for node in nodes:
        kids = node.get("children", [])
        if node.get("checked") is not None:  # a real task (has a checkbox)
            total += 1
            pr = match_pr(node["text"], node.get("pr_ref"), prs)
            node["pr"] = pr
            merged = bool(pr and pr.get("state") == "MERGED")
            if node["checked"] or merged:
                node["status"] = "done"
                node["checked"] = True
                done += 1
            elif pr and pr.get("state") == "OPEN":
                node["status"] = "in_progress"
            else:
                node["status"] = "planned"
        node.pop("pr_ref", None)
        cd, ct = fuse_roadmap(kids, prs)
        done += cd
        total += ct
        if node.get("checked") is None:  # group node — derive a rollup status from descendants
            node["status"] = "group"
    return done, total


def collect_roadmap(workdir: str, prs: List[Dict[str, Any]], rel: Optional[str]) -> Optional[Dict[str, Any]]:
    """Read + parse a room's roadmap file (config override or first candidate that exists), fuse
    with its PRs. Returns {source, nodes, progress, milestones} or None when no file is found."""
    candidates = [rel] if rel else ROADMAP_CANDIDATES
    path = next((os.path.join(workdir, c) for c in candidates if c and os.path.isfile(os.path.join(workdir, c))), None)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(120_000)
    except OSError:
        return None
    nodes = parse_roadmap(scrub_secrets(text))
    done, total = fuse_roadmap(nodes, prs)
    milestones: List[str] = []

    def walk(ns: List[Dict[str, Any]]) -> None:
        for n in ns:
            if n.get("milestone"):
                milestones.append(n["milestone"])
            walk(n.get("children", []))
    walk(nodes)
    return {"source": os.path.relpath(path, workdir), "nodes": nodes,
            "progress": {"done": done, "total": total}, "milestones": milestones}


def _int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def _iso_to_epoch(ts_iso: Optional[str]) -> Optional[float]:
    if not ts_iso:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _epoch_to_iso(epoch: float) -> Optional[str]:
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _age(ts_iso: Optional[str], now: float) -> Optional[float]:
    epoch = _iso_to_epoch(ts_iso)
    return None if epoch is None else now - epoch


# ---------------------------------------------------------------------------- #
# Snapshot build
# ---------------------------------------------------------------------------- #

def build_snapshot() -> Dict[str, Any]:
    now = time.time()
    panes = tmux_panes()
    # self-healing roster: registry UNION live tmux discovery (see discover_heads)
    roster = discover_heads(read_registry(), panes)
    config = load_rooms_config()

    heads: List[Dict[str, Any]] = []
    rooms: Dict[str, Dict[str, Any]] = {}
    pr_cache: Dict[str, List[Dict[str, Any]]] = {}
    room_workdirs: Dict[str, List[str]] = {}
    activity: List[Dict[str, Any]] = []
    heads_detail: Dict[str, Dict[str, Any]] = {}
    since_ts = now - ACTIVITY_WINDOW_S

    for name, workdir in roster:
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
        prompt = parse_prompt(cap) if status == "waiting-input" else None

        git = git_info(workdir)
        remote = git.pop("remote", None)

        # gather PRs per unique repo, cached (one gh call serves rooms + activity)
        if remote and remote not in pr_cache:
            pr_cache[remote] = gh_repo_prs(remote)

        # this head's in-progress commits (ahead of origin/main, within window)
        activity.extend(head_commit_events(workdir, name, room_id, since_ts))

        # per-head detail (served by /api/hq/head/{name}); memory_scope filled in below
        heads_detail[name] = {
            "room": room_id,
            "recent_commits": head_recent_commits(workdir),
            "fossils": head_fossils(name),
        }

        room = rooms.setdefault(room_id, {
            "id": room_id, "name": room_name, "repo": remote, "heads": [], "open_prs": [],
        })
        if remote and not room.get("repo"):
            room["repo"] = remote
        room["heads"].append(name)

        heads.append({
            "name": name,
            "room": room_id,
            "role": role_for(name, workdir),   # conductor | hq | head — for the Command category (A2)
            "workdir": workdir,
            "branch": git["branch"],
            "status": status,
            "current": current,
            "prompt": prompt,   # F6: the menu a waiting head is blocked on (else None)
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

    # external heads (B1): config-declared agents reporting via a bus heartbeat (e.g. win-gaia
    # on Windows) — invisible to tmux/registry. No git/fossils; status from the heartbeat file.
    for eh in collect_external_heads(config, now):
        rid = eh["room"]
        room = rooms.setdefault(rid, {
            "id": rid, "name": room_for(rid)[1], "repo": None, "heads": [], "open_prs": [],
        })
        room["heads"].append(eh["name"])
        heads.append(eh)
        heads_detail[eh["name"]] = {
            "room": rid, "recent_commits": [], "fossils": {"count": 0, "files": []},
            "source": eh["source"], "kind": eh["kind"], "tick": eh.get("tick"),
        }

    # attach open PRs to rooms (match PR branch -> head where possible) + emit PR activity
    branch_to_head = {h["branch"]: h["name"] for h in heads if h.get("branch")}
    seen_repos: set = set()
    for room in rooms.values():
        repo = room.get("repo") or ""
        prs = pr_cache.get(repo, [])
        for pr in open_prs_from(prs):
            pr["head"] = branch_to_head.get(pr.get("branch"))
            room["open_prs"].append(pr)
        if repo and repo not in seen_repos:  # PR events once per repo, not once per room
            seen_repos.add(repo)
            activity.extend(pr_events_from(prs, repo, room["id"], branch_to_head, since_ts))

    memory = collect_memory()

    # memory scope per head: the memory docs scoped to the head's project (room id)
    scope_by_room: Dict[str, List[Dict[str, Any]]] = {}
    for e in memory["index"]:
        if e.get("scope"):
            scope_by_room.setdefault(e["scope"], []).append(
                {"name": e["name"], "title": e["title"]}
            )
    for name, det in heads_detail.items():
        det["memory_scope"] = scope_by_room.get(det.get("room"), [])

    # category layer (A2): group heads above rooms per the hydra-hq rooms.config.json
    room_names = {r["id"]: r["name"] for r in rooms.values()}
    cat_by_head, categories = assign_categories(heads, room_names, config)
    for h in heads:
        h["category"] = cat_by_head.get(h["name"], h["room"])

    fleet = {
        "generated_at": int(now),
        "rooms": sorted(rooms.values(), key=lambda r: r["name"].lower()),
        "categories": categories,
        "heads": sorted(heads, key=lambda h: (h["room"], h["name"].lower())),
        "activity": finalize_activity(activity),
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
    heads_payload = {"generated_at": int(now), "heads": heads_detail}
    commands_payload = {"generated_at": int(now), **collect_commands()}

    # Living roadmap per room: nested checklist (epics→tasks) fused with the room's PR state.
    roadmap_cfg = config.get("roadmaps") or {}
    room_repo = {r["id"]: r.get("repo") for r in rooms.values()}
    roadmaps: Dict[str, Any] = {}
    for rid, wds in room_workdirs.items():
        rm = collect_roadmap(pick_room_workdir(wds) or wds[0],
                             pr_cache.get(room_repo.get(rid) or "", []), roadmap_cfg.get(rid))
        if rm:
            rm["repo"] = room_repo.get(rid)
            roadmaps[rid] = rm
    roadmap_payload = {"generated_at": int(now), "rooms": roadmaps}

    return {
        "fleet": fleet, "rooms_detail": rooms_detail, "memory": memory_payload,
        "heads_detail": heads_payload, "commands": commands_payload, "roadmap": roadmap_payload,
    }


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
    heads_detail = out["heads_detail"]
    ok = push_key(REDIS_KEY, fleet)
    ok_rooms = push_key(ROOMS_KEY, rooms_detail)
    ok_mem = push_key(MEMORY_KEY, memory)
    ok_heads = push_key(HEADS_KEY, heads_detail)
    ok_cmds = push_key(COMMANDS_KEY, out["commands"])
    ok_road = push_key(ROADMAP_KEY, out["roadmap"])
    if os.getenv("HQ_DEBUG"):
        print(json.dumps(fleet, indent=2))
        ndocs = sum(len(r["docs"]) for r in rooms_detail["rooms"].values())
        nfoss = sum(d["fossils"]["count"] for d in heads_detail["heads"].values())
        rm = out["roadmap"]["rooms"]
        print(f"[hq-collector] fleet={ok} rooms={ok_rooms} memory={ok_mem} heads={ok_heads} "
              f"commands={ok_cmds} roadmap={ok_road} heads={len(fleet['heads'])} rooms={len(fleet['rooms'])} "
              f"docs={ndocs} mem={len(memory['index'])} activity={len(fleet['activity'])} fossils={nfoss} "
              f"cmds={len(out['commands']['commands'])} roadmaps={ {k: v['progress'] for k, v in rm.items()} }")
    return 0 if (ok and ok_rooms and ok_mem and ok_heads and ok_cmds and ok_road) else 1


if __name__ == "__main__":
    raise SystemExit(main())
