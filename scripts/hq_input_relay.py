#!/usr/bin/env python3
"""HQ Console input relay — host-side `tmux send-keys` executor (CONSOLE.md Slice 2).

The dashboard backend runs in Docker and has no tmux, so it can't drive the host `hydra`
session directly. Instead the backend validates + audits + enqueues a job to Redis
(`hq:input:queue`); THIS host-side relay BLPOPs the queue and runs the actual
`tmux send-keys`. Same shape as the existing agent-bridge worker / hq-collector loop.

Why a relay (not tmux-in-the-container): keeps the box's tmux a host-only capability, avoids
tmux client/server protocol-version mismatches, and makes this one process the single,
auditable chokepoint for every keystroke HQ injects. The relay ONLY ever runs
`tmux send-keys -t <pane>` with a validated pane id — never a shell string from the bus.

Security: the queue is only writable by the Access-gated, localhost-bound backend. The relay
re-validates the pane id form AND that the pane is a live pane in the `hydra` session before
sending. It never evals/execs anything from the payload.

Install (host):  cp scripts/hq_input_relay.py ~/.local/bin/hq-input-relay.py
Run as a persistent service (mirrors hq-collector-loop.sh / the agent worker), e.g. a tiny
loop unit:  while :; do python3 ~/.local/bin/hq-input-relay.py; sleep 1; done
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

REDIS_CONTAINER = os.getenv("HQ_REDIS_CONTAINER", "tdbox-redis")
INPUT_QUEUE = "hq:input:queue"
RESULT_PREFIX = "hq:input:result:"   # per-job delivery result (for the console's delivery badge)
RESULT_TTL_S = 300
TMUX_SESSION = os.getenv("HQ_TMUX_SESSION", "hydra")
BLPOP_TIMEOUT = 5
_PANE_RE = re.compile(r"^%\d+$")


# ---------------------------------------------------------------------------- pure helpers
def parse_job(value: str) -> Optional[Dict[str, Any]]:
    try:
        job = json.loads(value)
    except (ValueError, TypeError):
        return None
    return job if isinstance(job, dict) else None


def valid_pane(pane: Any) -> bool:
    return isinstance(pane, str) and bool(_PANE_RE.match(pane))


# ---------------------------------------------------------------------------- tmux + redis I/O
def _live_panes() -> set:
    """Pane ids currently in the hydra session — the relay only sends to one of these."""
    out = subprocess.run(
        ["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{pane_id}"],
        capture_output=True, text=True, timeout=8,
    ).stdout
    panes = set()
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] == TMUX_SESSION:
            panes.add(parts[1])
    return panes


def send_to_pane(pane: str, text: str) -> bool:
    """Text first (literal), THEN a separate Enter — the multi-line gotcha (a newline inside
    `text` must not submit early; only the trailing Enter submits). No shell: argv list only."""
    try:
        subprocess.run(["tmux", "send-keys", "-t", pane, "-l", "--", text], check=True, timeout=8)
        subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=True, timeout=8)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        print(f"[hq-input-relay] send failed pane={pane}: {e}", file=sys.stderr)
        return False


def blpop_job() -> Optional[Dict[str, Any]]:
    """Block up to BLPOP_TIMEOUT for a job via the container's redis-cli (mirrors the collector's
    docker-exec pattern; no host redis client / published port assumed)."""
    try:
        p = subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli", "BLPOP", INPUT_QUEUE, str(BLPOP_TIMEOUT)],
            capture_output=True, text=True, timeout=BLPOP_TIMEOUT + 5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    lines = [ln for ln in p.stdout.splitlines() if ln != ""]
    # redis-cli BLPOP prints: <key>\n<value>  (empty on timeout)
    if len(lines) >= 2 and lines[0] == INPUT_QUEUE:
        return parse_job(lines[1])
    return None


def write_result(jid: Optional[str], ok: bool) -> None:
    """Record a job's delivery result so the console can flip its per-message badge to
    delivered ✓ / failed ✗ (instead of a silently-stuck 'sending')."""
    if not jid:
        return
    payload = json.dumps({"ok": ok, "ts": int(time.time())})
    try:
        subprocess.run(["docker", "exec", REDIS_CONTAINER, "redis-cli", "SETEX",
                        RESULT_PREFIX + str(jid), str(RESULT_TTL_S), payload],
                       capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        pass


def handle(job: Dict[str, Any], live: set) -> None:
    pane, text, jid = job.get("pane"), job.get("text"), job.get("id")
    if not valid_pane(pane):
        print(f"[hq-input-relay] reject bad pane: {pane!r}", file=sys.stderr)
        write_result(jid, False)
        return
    if pane not in live:
        print(f"[hq-input-relay] pane {pane} not in '{TMUX_SESSION}' session — dropping", file=sys.stderr)
        write_result(jid, False)
        return
    if not isinstance(text, str) or not text:
        print("[hq-input-relay] reject empty text", file=sys.stderr)
        write_result(jid, False)
        return
    ok = send_to_pane(pane, text)
    write_result(jid, ok)
    print(f"[hq-input-relay] {'sent' if ok else 'FAILED'} head={job.get('head')} pane={pane} "
          f"by={job.get('by')} id={job.get('id')} len={len(text)}")


def main() -> int:
    # One blocking drain cycle, then exit so a supervising loop can restart us (crash-safe).
    job = blpop_job()
    if job is None:
        return 0
    handle(job, _live_panes())
    # opportunistically drain anything else already queued without blocking
    while True:
        try:
            p = subprocess.run(
                ["docker", "exec", REDIS_CONTAINER, "redis-cli", "LPOP", INPUT_QUEUE],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            break
        val = p.stdout.strip()
        if not val:
            break
        more = parse_job(val)
        if more:
            handle(more, _live_panes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
