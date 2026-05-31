"""
Crack-a-Dawn — synthesis (the one Opus step, dedicated `claude -p`).

Receives the scored/flagged movers + grounding headlines and produces the brief.
The agent does the catalyst RESEARCH itself with scoped read-only tools (WebSearch,
WebFetch, the *-pp-cli data CLIs) — we don't hand-code every fetcher. Runs as a
dedicated `claude -p` on the box, separate from the interactive pool.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Dict, List, Optional, Sequence

from .scoring import MoverScore, TIER_EMOJI

logger = logging.getLogger("crack_a_dawn.synthesize")

CLAUDE_BIN = os.getenv("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
SYNTH_TIMEOUT = int(os.getenv("CRACKDAWN_SYNTH_TIMEOUT", "900"))

ALLOWED_TOOLS = [
    "WebSearch", "WebFetch",
    "Bash(finnhub-pp-cli:*)", "Bash(sec-edgar-pp-cli:*)",
    "Bash(usaspending-pp-cli:*)", "Bash(fred-pp-cli:*)",
]

SYSTEM = (
    "You are Tradeskeebot, Schyler's market-intelligence analyst. Sober, data-driven, "
    "no hype, no filler, no disclaimers. You write a pre-market brief that a serious swing "
    "trader reads in 2 minutes before the open. Lead with what needs a decision. Cite the "
    "catalyst and source. Classify each catalyst (earnings / M&A / analyst rating / guidance / "
    "regulatory / insider / gov't contract / index / macro-sector) and tag short- vs long-term. "
    "If several names moved on ONE shared catalyst, consolidate them into a sector story. For "
    "every name give one blunt line on what it means for THIS book (held vs watch, size). Use "
    "your tools to verify the actual catalyst — do not speculate when you can check."
)


def _fmt_mover(s: MoverScore, held_wt: float, headlines: List[Dict[str, str]]) -> str:
    book = f"HELD {held_wt*100:.0f}% of book" if held_wt > 0 else "watchlist"
    lines = [
        f"### {TIER_EMOJI[s.tier]} {s.ticker}  [{s.tier}]",
        f"- move {s.move_pct:+.1f}% | {s.sigma:+.1f}σ vs its 30d range | "
        f"idiosyncratic residual {s.residual_pct:+.1f}% | "
        f"RVOL {s.rvol:.1f}x" if s.rvol is not None else
        f"- move {s.move_pct:+.1f}% | {s.sigma:+.1f}σ | residual {s.residual_pct:+.1f}%",
        f"- position: {book}",
        f"- flag reasons: {'; '.join(s.reasons) or '—'}",
    ]
    if headlines:
        lines.append("- recent headlines (verify/expand with your tools):")
        for h in headlines[:5]:
            lines.append(f"    • {h['headline']} ({h['source']})")
    return "\n".join(lines)


def build_prompt(
    date_str: str,
    market_context: str,
    flagged: Sequence[MoverScore],
    held: Dict[str, float],
    grounding: Dict[str, List[Dict[str, str]]],
) -> str:
    blocks = [
        _fmt_mover(s, held.get(s.ticker, 0.0), grounding.get(s.ticker, []))
        for s in flagged
    ]
    movers = "\n\n".join(blocks) if blocks else "(no names cleared the attention threshold)"
    return f"""Write Schyler's **Crack-a-Dawn** pre-market brief for **{date_str}**.

MARKET CONTEXT: {market_context}

These names were flagged by the Attention Score (already ranked; σ = move vs the stock's
own volatility, residual = move after stripping market/beta). For each, research WHY it
moved overnight and write it up:

{movers}

OUTPUT — clean markdown, in this order:
1. **Lead:** "N things need your attention" — the 🔴/❓ names in one line each (ticker, the move,
   the catalyst in a few words, and the action implication). If none are 🔴/❓, say the morning is quiet
   and give the single most-notable 🟡.
2. **Sector clusters** (only if ≥2 names share one catalyst): the shared story + the names under it.
3. **Per-name detail** for each flagged name: catalyst (classified, short/long-term, with source),
   the read, and the blunt one-line "for your book" implication.
Keep it tight. No preamble, no sign-off — start at the Lead."""


def synthesize(prompt: str) -> Optional[str]:
    """Run the dedicated claude -p and return the brief markdown (or None on failure)."""
    cmd = [CLAUDE_BIN, "-p", "--allowedTools", *ALLOWED_TOOLS]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=SYNTH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("synthesis timed out after %ss", SYNTH_TIMEOUT)
        return None
    if proc.returncode != 0:
        logger.error("claude -p failed (%s): %s", proc.returncode, proc.stderr[:500])
        return None
    return _clean(proc.stdout)


def _clean(out: str) -> Optional[str]:
    """Trim any pre-brief preamble — start at the first markdown header line."""
    out = (out or "").strip()
    if not out:
        return None
    for i, line in enumerate(out.splitlines()):
        if line.lstrip().startswith("#"):
            return "\n".join(out.splitlines()[i:]).strip()
    return out
