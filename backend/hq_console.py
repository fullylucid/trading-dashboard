"""HQ Console — read a head's live conversation transcript (CONSOLE.md, Slice 1).

HQ runs in WSL alongside the `hydra` tmux session, so it can read any head's Claude Code
transcript `.jsonl` directly and render it as a rich chat view (live-tailed). The Dockerized
backend reaches the transcripts via a read-only bind-mount of ~/.claude/projects (see
docker-compose.box.yml); this module turns the newest transcript into renderable turns.

Read-only and behind Cloudflare Access SSO. Token-shaped secrets are scrubbed defense-in-depth
even though the operator is viewing their own heads.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Container path bind-mounted from /home/user/.claude/projects (ro); defaults to the host path
# so the backend can run directly on the box for testing.
PROJECTS_DIR = os.getenv("HQ_PROJECTS_DIR", os.path.expanduser("~/.claude/projects"))

DEFAULT_LIMIT = 60          # turns returned on a cold load
TOOL_INPUT_MAX = 4000       # cap tool_use input / tool_result bodies (UI collapses them)
TEXT_MAX = 20000            # generous cap on a single text/thinking block

# Console input (Slice 2). The backend (in Docker, no tmux) enqueues a validated command to
# Redis; the host-side relay (scripts/hq_input_relay.py) runs the actual `tmux send-keys`.
INPUT_QUEUE = "hq:input:queue"   # rpush jobs here; the relay BLPOPs
INPUT_AUDIT = "hq:input:audit"   # capped list of every input sent (who/when/head/text)
INPUT_AUDIT_MAX = 500
INPUT_TEXT_MAX = 10000
_PANE_RE = re.compile(r"^%\d+$")  # tmux pane id form — the relay only ever targets one of these

# Photo / document upload (F4). The backend saves the file to a shared uploads dir (bind-mounted),
# then sends the head a message referencing the file's ABSOLUTE HOST path so its Claude Code Reads
# it. UPLOADS_DIR is where the backend writes (container path); UPLOADS_DIR_HOST is the path the
# head sees (referenced in the message) — same dir, two mount views (cf. FINTUBE_VISION_DIR).
UPLOADS_DIR = os.getenv("HQ_UPLOADS_DIR", "/home/user/hydra-worktrees/.hq-uploads")
UPLOADS_DIR_HOST = os.getenv("HQ_UPLOADS_DIR_HOST", "/home/user/hydra-worktrees/.hq-uploads")
UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tiff"}

_SECRET_PATTERNS = [
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\b(token|secret|api[-_]?key|password|passwd|bearer)\b\s*[=:]\s*\S+"),
]


def scrub(text: Optional[str]) -> str:
    if not text:
        return ""
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def transcript_dir_name(workdir: str) -> str:
    """Claude Code's project-dir slug: every non [A-Za-z0-9-] char -> '-' (the archive's rule).
    e.g. /home/user/hydra-worktrees/trading-dashboard__hq -> -home-user-...-dashboard--hq."""
    return re.sub(r"[^A-Za-z0-9-]", "-", workdir.rstrip("/"))


def newest_transcript(workdir: str, projects_dir: str = PROJECTS_DIR) -> Optional[str]:
    d = os.path.join(projects_dir, transcript_dir_name(workdir))
    try:
        files = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl")]
    except OSError:
        return None
    return max(files, key=os.path.getmtime) if files else None


def _trunc(s: str, n: int) -> str:
    s = scrub(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _stringify(content: Any) -> str:
    """tool_result content can be a string or a list of blocks; flatten to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "image":
                    out.append("[image]")
                else:
                    out.append(json.dumps(b)[:200])
            else:
                out.append(str(b))
        return "\n".join(out)
    return json.dumps(content) if content is not None else ""


def parse_event(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One transcript event -> a renderable turn, or None if it has nothing to show.
    Block kinds: text | thinking | tool_use | tool_result (mirrors the Claude-app chat)."""
    etype = d.get("type")
    if etype not in ("user", "assistant", "system"):
        return None
    msg = d.get("message") or {}
    content = msg.get("content")
    blocks: List[Dict[str, Any]] = []

    if isinstance(content, str):
        if content.strip():
            blocks.append({"kind": "text", "text": _trunc(content, TEXT_MAX)})
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text" and b.get("text", "").strip():
                blocks.append({"kind": "text", "text": _trunc(b["text"], TEXT_MAX)})
            elif bt == "thinking" and b.get("thinking", "").strip():
                blocks.append({"kind": "thinking", "text": _trunc(b["thinking"], TEXT_MAX)})
            elif bt == "tool_use":
                blocks.append({
                    "kind": "tool_use",
                    "name": b.get("name", "tool"),
                    "input": _trunc(json.dumps(b.get("input", {}), ensure_ascii=False), TOOL_INPUT_MAX),
                })
            elif bt == "tool_result":
                blocks.append({
                    "kind": "tool_result",
                    "text": _trunc(_stringify(b.get("content")), TOOL_INPUT_MAX),
                    "is_error": bool(b.get("is_error")),
                })

    if not blocks:
        return None
    return {
        "uuid": d.get("uuid"),
        "type": etype,
        "timestamp": d.get("timestamp"),
        "blocks": blocks,
    }


def read_turns(
    path: str, limit: int = DEFAULT_LIMIT, after: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """Parse turns from a transcript. With `after` (a byte offset) only the bytes past it are
    parsed (incremental live-tail); otherwise the last `limit` turns are returned. Returns
    (turns, cursor) where cursor is the file size to poll from next."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], 0

    turns: List[Dict[str, Any]] = []
    try:
        with open(path, "rb") as f:
            if after is not None and 0 <= after <= size:
                f.seek(after)
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return [], size

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        turn = parse_event(evt)
        if turn:
            turns.append(turn)

    if after is None and len(turns) > limit:
        turns = turns[-limit:]
    return turns, size


# ---------------------------------------------------------------------------- console input
def clean_input_text(text: Any) -> str:
    """Validate + normalize composer text. Strips a trailing newline (the relay sends a separate
    Enter), caps length. Raises ValueError on empty/oversize — the route turns that into a 400."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    t = text.rstrip("\n")
    if not t.strip():
        raise ValueError("text is empty")
    if len(t) > INPUT_TEXT_MAX:
        raise ValueError("text too long")
    return t


def valid_pane(pane: Any) -> bool:
    return isinstance(pane, str) and bool(_PANE_RE.match(pane))


def input_job(head: str, pane: str, text: str, by: str, now: float, jid: str) -> Dict[str, Any]:
    """The command the host relay consumes. `pane` is a tmux pane id (validated) — never a
    shell string; the relay only ever runs `tmux send-keys -t <pane>`, nothing interpolated."""
    return {"id": jid, "head": head, "pane": pane, "text": text, "by": by, "ts": int(now)}


def is_image(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in _IMAGE_EXTS


def safe_upload_name(filename: str, jid: str) -> str:
    """A collision-free, path-safe upload filename: <jid>-<sanitized basename>. Strips any
    directory components and unusual chars so a malicious name can't escape the uploads dir."""
    base = os.path.basename(filename or "file")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "file"
    return f"{jid[:8]}-{base[:80]}"


def upload_message(caption: str, host_path: str, image: bool) -> str:
    """One-attachment convenience wrapper around build_message."""
    return build_message(caption, [{"path": host_path, "image": image}])


def build_message(caption: str, attachments: Any) -> str:
    """The message send-keys'd to the head: the user's caption (if any) then one clear attachment
    signal per file — ``[image attached] <abs-path>`` / ``[file attached] <abs-path>`` — so the
    head reliably Reads each regardless of caption. Supports MULTIPLE attachments per message.
    Verified delivery format (Schyler, 2026-06-09)."""
    cap = (caption or "").strip()
    lines = []
    for a in (attachments or []):
        if not isinstance(a, dict) or not a.get("path"):
            continue
        tag = "[image attached]" if a.get("image") else "[file attached]"
        lines.append(f"{tag} {a['path']}")
    parts = ([cap] if cap else []) + lines
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("nothing to send")
    if len(text) > INPUT_TEXT_MAX:
        raise ValueError("message too long")
    return text
