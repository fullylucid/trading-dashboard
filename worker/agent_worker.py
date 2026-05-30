#!/usr/bin/env python3
"""
Agent Worker - runs on the always-on WSL2 box (Claude Max quota, free).

Long-polls the cloud FastAPI app for jobs, runs `claude -p` locally with the
home-directory soul/memory loaded (HOME=/home/user), streams output back, and
for `code` jobs opens a PR (never pushes to main directly).

Two credentials are never mixed: this worker only ever presents
AGENT_WORKER_TOKEN, and only to /api/agent/next and /api/agent/result.

Single job at a time. Never crashes the loop: every job is wrapped so a failure
posts an error result and moves on. Idempotent: a job_id is processed once.

Config (env, typically via the systemd EnvironmentFile):
    AGENT_BACKEND_URL   e.g. https://app.example.com
    AGENT_WORKER_TOKEN  the shared worker bearer token
    AGENT_REPO_DIR      dedicated repo clone the worker edits (default ~/trading-dashboard-agent)
    AGENT_BASE_BRANCH   PR base branch (default main)
    CLAUDE_BIN          path to the claude CLI (default "claude")
    JOB_TIMEOUT_SECS    wall-clock cap per claude run (default 1800)
"""

import os
import re
import sys
import json
import time
import uuid
import fcntl
import shlex
import logging
import subprocess
from pathlib import Path
from contextlib import contextmanager

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - agent_worker - %(levelname)s - %(message)s",
)
logger = logging.getLogger("agent_worker")

BACKEND_URL = os.environ.get("AGENT_BACKEND_URL", "").rstrip("/")
WORKER_TOKEN = os.environ.get("AGENT_WORKER_TOKEN", "")
HOME_DIR = os.environ.get("HOME", "/home/user")
REPO_DIR = os.environ.get("AGENT_REPO_DIR", os.path.join(HOME_DIR, "trading-dashboard-agent"))
BASE_BRANCH = os.environ.get("AGENT_BASE_BRANCH", "main")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT_SECS", "1800"))
POLL_WAIT = int(os.environ.get("POLL_WAIT_SECS", "25"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECS", "2"))  # idle gap between non-blocking polls

STATE_DIR = Path(HOME_DIR) / ".local" / "share" / "agent-bridge"
CONV_DIR = STATE_DIR / "conversations"
SEEN_FILE = STATE_DIR / "seen_jobs.txt"
# Cross-instance lock so only one `code`/`approval` job touches the shared
# AGENT_REPO_DIR clone at a time — read-only jobs (data/brainstorm/scan) never
# take it, so they run fully in parallel across the worker pool.
CODE_LOCK_FILE = STATE_DIR / "code.lock"

# Pool: each systemd template instance passes its number via AGENT_WORKER_ID
# (%i). Falls back to PID for a standalone run. Logged for traceability.
WORKER_ID = os.environ.get("AGENT_WORKER_ID", str(os.getpid()))

# Max-subscription throttle handling: when `claude -p` reports a usage/rate
# limit, back off and retry the SAME job locally rather than failing it.
THROTTLE_RETRIES = int(os.environ.get("CLAUDE_THROTTLE_RETRIES", "3"))
THROTTLE_MARKERS = (
    "usage limit", "rate limit", "rate_limit", "overloaded",
    "limit reached", "too many requests", "429", "529",
)

READONLY_TOOLS = "Read,Glob,Grep,Bash(git diff:*),Bash(ls:*),Bash(cat:*),WebSearch,WebFetch"


@contextmanager
def code_lock():
    """Serialize repo-mutating jobs across all pool instances (flock on a
    shared lockfile). Read-only jobs do not acquire this."""
    CODE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    f = open(CODE_LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _looks_throttled(text: str, stderr: str, returncode: int) -> bool:
    if returncode == 0:
        return False
    blob = f"{text}\n{stderr}".lower()
    return any(m in blob for m in THROTTLE_MARKERS)

# Secrets that must never end up in a diff/PR
SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{20,}",
    r"gho_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]
SECRET_PATH_HINTS = (".env", ".pem", "id_rsa", "id_ed25519", ".credentials.json")


# ============================================================================
# Backend I/O
# ============================================================================

def _headers():
    return {"Authorization": f"Bearer {WORKER_TOKEN}"}


def fetch_next(client: httpx.Client):
    try:
        resp = client.get(
            f"{BACKEND_URL}/api/agent/next",
            headers=_headers(),
            timeout=20,
        )
    except httpx.HTTPError as e:
        logger.warning(f"poll failed: {e}")
        time.sleep(3)
        return None
    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        logger.warning(f"/next returned {resp.status_code}: {resp.text[:200]}")
        time.sleep(3)
        return None
    return resp.json()


def post_result(client: httpx.Client, job_id, seq, type_, content,
                conversation_id=None, approval_kind=None, pr_url=None,
                title=None, claude_session_id=None):
    body = {
        "job_id": job_id, "seq": seq, "type": type_, "content": content,
        "conversation_id": conversation_id, "approval_kind": approval_kind,
        "pr_url": pr_url, "title": title, "claude_session_id": claude_session_id,
    }
    try:
        client.post(f"{BACKEND_URL}/api/agent/result", json=body,
                    headers=_headers(), timeout=30)
    except httpx.HTTPError as e:
        logger.error(f"post_result failed (job {job_id} seq {seq}): {e}")


# ============================================================================
# Idempotency + transcript persistence
# ============================================================================

def _ensure_dirs():
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.touch(exist_ok=True)


def already_seen(job_id: str) -> bool:
    try:
        return job_id in SEEN_FILE.read_text().splitlines()
    except FileNotFoundError:
        return False


def mark_seen(job_id: str):
    with SEEN_FILE.open("a") as f:
        f.write(job_id + "\n")


def append_transcript(conversation_id: str, entry: dict):
    path = CONV_DIR / f"{conversation_id}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ============================================================================
# Claude invocation
# ============================================================================

def _git(args, cwd=REPO_DIR, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check,
                          capture_output=True, text=True)


def run_claude(prompt: str, allowed_tools: str = None, resume_session: str = None,
               allow_edits: bool = False, cwd: str = None) -> tuple[str, str]:
    """Run `claude -p` and return (stdout_text, session_id)."""
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if resume_session:
        cmd += ["--resume", resume_session]
    if allowed_tools:
        cmd += ["--allowedTools", allowed_tools]
    if allow_edits:
        cmd += ["--permission-mode", "acceptEdits"]
    env = dict(os.environ, HOME=HOME_DIR)
    logger.info(f"[w{WORKER_ID}] claude: {shlex.join(cmd[:4])} ... (edits={allow_edits})")

    attempt = 0
    while True:
        proc = subprocess.run(cmd, cwd=cwd or HOME_DIR, env=env,
                              capture_output=True, text=True, timeout=JOB_TIMEOUT)
        out = proc.stdout.strip()
        session_id = None
        text = out
        # --output-format json yields a JSON envelope; extract result + session_id
        try:
            data = json.loads(out)
            text = data.get("result", out)
            session_id = data.get("session_id")
        except json.JSONDecodeError:
            pass

        # Max-subscription throttle: back off and retry the same job rather
        # than burning it. Capped retries; exponential backoff (30s, 60s, 120s).
        if _looks_throttled(text, proc.stderr, proc.returncode) and attempt < THROTTLE_RETRIES:
            backoff = min(30 * (2 ** attempt), 240)
            logger.warning(f"[w{WORKER_ID}] claude throttled "
                           f"(attempt {attempt + 1}/{THROTTLE_RETRIES}); backing off {backoff}s")
            time.sleep(backoff)
            attempt += 1
            continue

        if proc.returncode != 0 and not text:
            text = proc.stderr.strip() or f"claude exited {proc.returncode}"
        return text, session_id


def generate_title(content: str) -> str:
    try:
        title, _ = run_claude(
            f"Summarize this request as a 3-5 word title. Reply with ONLY the title, no quotes:\n\n{content}",
            allowed_tools="",  # no tools
        )
        return title.strip().strip('"')[:60] or "New chat"
    except Exception as e:
        logger.warning(f"title gen failed: {e}")
        return "New chat"


# ============================================================================
# Approval / PR flow (code jobs)
# ============================================================================

def scan_for_secrets(diff: str, changed_files: list[str]) -> str | None:
    for pat in SECRET_PATTERNS:
        if re.search(pat, diff):
            return f"diff matched secret pattern {pat!r}"
    for fp in changed_files:
        if any(h in fp for h in SECRET_PATH_HINTS):
            return f"changed file looks sensitive: {fp}"
    return None


def open_pr_for_changes(job_id: str) -> tuple[str | None, str]:
    """Returns (pr_url, summary). Returns (None, summary) if nothing to do or aborted."""
    status = _git(["status", "--porcelain"]).stdout.strip()
    if not status:
        return None, "No changes were made."

    diff = _git(["diff", f"origin/{BASE_BRANCH}", "--", "."], check=False).stdout
    if not diff:
        diff = _git(["diff"]).stdout
    changed = [l[3:] for l in status.splitlines()]

    reason = scan_for_secrets(diff, changed)
    if reason:
        _git(["checkout", "--", "."], check=False)
        _git(["clean", "-fd"], check=False)
        return None, f"ABORTED: potential secret in changes ({reason}). Changes discarded."

    slug = job_id[:8]
    branch = f"agent/{slug}"
    _git(["checkout", "-b", branch])
    _git(["add", "-A"])
    _git(["commit", "-m", f"agent: changes for job {slug}"])
    _git(["push", "-u", "origin", branch])
    pr = subprocess.run(
        ["gh", "pr", "create", "--base", BASE_BRANCH, "--head", branch,
         "--title", f"agent: job {slug}", "--body", "Automated change from the messenger agent. Review before merge."],
        cwd=REPO_DIR, capture_output=True, text=True,
    )
    pr_url = pr.stdout.strip().splitlines()[-1] if pr.returncode == 0 else None
    summary = f"Opened PR for {len(changed)} changed file(s):\n" + "\n".join(f"- {f}" for f in changed[:20])
    return pr_url, summary


def handle_approval(job: dict, client: httpx.Client):
    action = job.get("action")
    target = job.get("target_job_id", "")[:8]
    branch = f"agent/{target}"
    if action == "merge":
        res = subprocess.run(["gh", "pr", "merge", branch, "--merge", "--delete-branch"],
                             cwd=REPO_DIR, capture_output=True, text=True)
        msg = "Merged PR -> deploying." if res.returncode == 0 else f"Merge failed: {res.stderr[:200]}"
    else:
        res = subprocess.run(["gh", "pr", "close", branch, "--delete-branch"],
                             cwd=REPO_DIR, capture_output=True, text=True)
        msg = "PR rejected and closed." if res.returncode == 0 else f"Close failed: {res.stderr[:200]}"
    post_result(client, job["job_id"], 1, "final", msg,
                conversation_id=job.get("conversation_id"))


# ============================================================================
# Dispatch
# ============================================================================

def prepare_repo():
    """Make sure the dedicated clone is on a clean base branch, up to date."""
    _git(["fetch", "origin", BASE_BRANCH], check=False)
    _git(["checkout", BASE_BRANCH], check=False)
    _git(["reset", "--hard", f"origin/{BASE_BRANCH}"], check=False)
    _git(["clean", "-fd"], check=False)


def handle_job(job: dict, client: httpx.Client):
    job_id = job["job_id"]
    kind = job.get("kind", "brainstorm")
    conversation_id = job.get("conversation_id")
    content = job.get("content", "")

    if kind == "approval":
        with code_lock():  # gh pr merge/close touches the shared clone
            handle_approval(job, client)
        return

    # Conversation continuity via claude --resume (session id supplied by backend)
    resume = job.get("resume_session") or None

    title = generate_title(content) if job.get("needs_title") else None

    if kind in ("data", "brainstorm", "scan"):
        text, session_id = run_claude(content, allowed_tools=READONLY_TOOLS,
                                      resume_session=resume, allow_edits=False)
        post_result(client, job_id, 1, "final", text,
                    conversation_id=conversation_id, title=title,
                    claude_session_id=session_id)
        if conversation_id:
            append_transcript(conversation_id, {"job_id": job_id, "kind": kind,
                                                "request": content, "response": text})
        return

    if kind == "code":
        # Hold the lock across reset/edit/branch/push so two pool instances
        # can't clobber the single shared clone. Result-posting stays outside.
        with code_lock():
            prepare_repo()
            text, session_id = run_claude(content, resume_session=resume,
                                          allow_edits=True, cwd=REPO_DIR)
            pr_url, summary = open_pr_for_changes(job_id)
        body = f"{text}\n\n---\n{summary}"
        post_result(client, job_id, 1, "final", body,
                    conversation_id=conversation_id,
                    approval_kind="pr" if pr_url else None,
                    pr_url=pr_url, title=title, claude_session_id=session_id)
        if conversation_id:
            append_transcript(conversation_id, {"job_id": job_id, "kind": kind,
                                                "request": content, "response": body,
                                                "pr_url": pr_url})
        return

    post_result(client, job_id, 1, "error", f"Unknown job kind: {kind}",
                conversation_id=conversation_id)


# ============================================================================
# Main loop
# ============================================================================

def main():
    if not BACKEND_URL or not WORKER_TOKEN:
        logger.error("AGENT_BACKEND_URL and AGENT_WORKER_TOKEN are required")
        sys.exit(1)
    _ensure_dirs()
    logger.info(f"[w{WORKER_ID}] agent worker online -> {BACKEND_URL} (repo={REPO_DIR})")

    with httpx.Client() as client:
        while True:
            job = fetch_next(client)
            if job is None:
                time.sleep(POLL_INTERVAL)
                continue
            job_id = job.get("job_id", "")
            if already_seen(job_id):
                logger.info(f"skip duplicate job {job_id[:8]}")
                continue
            mark_seen(job_id)
            logger.info(f"job {job_id[:8]} kind={job.get('kind')}")
            try:
                handle_job(job, client)
            except subprocess.TimeoutExpired:
                post_result(client, job_id, 1, "error", "Job timed out.",
                            conversation_id=job.get("conversation_id"))
            except Exception as e:
                logger.exception("job failed")
                post_result(client, job_id, 1, "error", f"Worker error: {e}",
                            conversation_id=job.get("conversation_id"))


if __name__ == "__main__":
    main()
