"""
2Chainz — the portfolio strategist (dedicated `claude -p` per message).

Advisory ONLY: it analyzes the book, pulls live data, argues theses, drafts ideas —
it NEVER places a trade (those stay propose-then-confirm, Schyler's call). Read-only
tools. Conversational, Telegram-sized replies grounded in the live book + the brief.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

from . import context, conversation

logger = logging.getLogger("twochainz.agent")
CLAUDE_BIN = os.getenv("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
TIMEOUT = int(os.getenv("TWOCHAINZ_TIMEOUT", "600"))

ALLOWED_TOOLS = [
    "WebSearch", "WebFetch",
    "Bash(finnhub-pp-cli:*)", "Bash(sec-edgar-pp-cli:*)",
    "Bash(usaspending-pp-cli:*)", "Bash(fred-pp-cli:*)",
    "Bash(opts:*)",  # the options engine — chains, Greeks, strategies
]

SYSTEM = (
    "You are 2Chainz, Schyler's portfolio strategist — the desk he talks to after the "
    "morning Crack-a-Dawn brief. You know his live book and today's brief (given below). Sharp, "
    "opinionated, sober — no hype, no hedging filler, no disclaimers. You discuss opportunities, "
    "developments, risk, position sizing, and theses, and you push back when his read is off. "
    "ADVISORY ONLY: you never place, modify, or cancel a trade — those are his call and are "
    "propose-then-confirm. You may draft a precise trade IDEA (entry/size/stop/thesis) for him to "
    "execute himself, clearly framed as a proposal. Use your read-only tools to verify with live "
    "data before asserting. For options you have the `opts` CLI — run it before recommending any "
    "options trade: `opts chain SYM`, `opts strategy SYM --kind call|put --dir bull|bear` (verticals), "
    "`opts income SYM --kind put|call` (cash-secured puts / covered calls), `opts condor SYM` (iron "
    "condors), `opts strangle SYM --side short|long`, `opts straddle SYM --side long|short`, and "
    "`opts wheel SYM` (the guided Wheel — tells you if he holds the shares and the next CSP/CC to sell). "
    "This is a Telegram chat: reply conversationally and concisely "
    "(a few short paragraphs or tight bullets, emojis ok, links when useful). Answer the latest "
    "message; the transcript is for continuity."
)


def respond(user_message: str) -> Optional[str]:
    """Run one strategist turn over the live context + conversation history."""
    prompt = (
        f"=== LIVE CONTEXT ===\n{context.gather()}\n\n"
        f"=== CONVERSATION SO FAR ===\n{conversation.as_transcript()}\n\n"
        f"=== SCHYLER'S NEW MESSAGE ===\n{user_message}\n\n"
        "Reply as 2Chainz. No preamble — just your answer."
    )
    cmd = [CLAUDE_BIN, "-p", "--append-system-prompt", SYSTEM, "--allowedTools", *ALLOWED_TOOLS]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.error("strategist timed out")
        return None
    if proc.returncode != 0:
        logger.error("claude -p failed (%s): %s", proc.returncode, proc.stderr[:400])
        return None
    return (proc.stdout or "").strip() or None
