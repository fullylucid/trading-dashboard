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

from .scoring import MoverScore, ball

logger = logging.getLogger("crack_a_dawn.synthesize")

CLAUDE_BIN = os.getenv("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
SYNTH_TIMEOUT = int(os.getenv("CRACKDAWN_SYNTH_TIMEOUT", "900"))

ALLOWED_TOOLS = [
    "WebSearch", "WebFetch",
    "Bash(finnhub-pp-cli:*)", "Bash(sec-edgar-pp-cli:*)",
    "Bash(usaspending-pp-cli:*)", "Bash(fred-pp-cli:*)",
]

SYSTEM = (
    "You are Tradeskeebot, Schyler's market-intelligence analyst. Sober, data-driven, no hype, "
    "no disclaimers. You write his DAILY pre-market briefing — this is the only thing he reads, "
    "so it must STAND ALONE and actually explain things: real context, the mechanism behind each "
    "move, not abbreviations. Classify each catalyst (earnings / M&A / analyst rating / guidance / "
    "regulatory / insider / gov't contract / index / macro-sector) and tag short- vs long-term. "
    "Consolidate names that moved on one shared catalyst. Always say what it means for THIS book "
    "(held vs watch, size). Verify catalysts with your tools and include a good source link per "
    "name — do not speculate when you can check."
)


_OUTPUT_TEMPLATE = """
BALL CONVENTION: the colored ball encodes DIRECTION — 🟢 if UP (bullish), 🔴 if DOWN (bearish).
Attention level is a separate text tag [ACT]/[KNOW]/[NOTE]; append ❓ for an UNEXPLAINED (high-σ,
no catalyst) name. So a bullish must-act name is "🟢 NOW [ACT]"; a bearish one is "🔴 XYZ [ACT]".

OUTPUT — a RICH but scannable DAILY briefing as ONE Telegram message. It is the whole product, so
EXPLAIN, don't abbreviate. Hard limit: keep the TOTAL under ~3400 characters (links included).

FORMATTING is Telegram Markdown — follow exactly:
- *single-asterisk bold* (NOT **double**); • for bullets; [text](url) for links; emojis freely.
- NO "#" markdown headers. Do NOT use stray _ * [ ] characters inside prose (they break Telegram).
- Blank line between blocks.

STRUCTURE (fill the placeholders):
*🌅 Crack-a-Dawn — (today's date)*
_(one line of market context: indices, VIX, the overnight theme)_

*⚡ Needs your attention (N)*

Then, most-important first, fully detail the top ~4 flagged names. If more were flagged, end with a
one-line "*+M more:* TICKERS". Each detailed name is a block:

(🟢 or 🔴) *TICKER* [TIER] (+X.X%)  ·  _(N-sigma vs its range, residual, RVOL — in plain words)_
• 📰 *Why:* 2-3 real sentences — what actually happened, catalyst classified, short- vs long-term, with numbers.
• 💼 *Your book:* held X% / watching — the blunt action (trim / add on pullback / don't chase / tighten stop).
• 🔗 [source](url)

If ≥2 names share one catalyst, add a *🧭 Sector read:* line tying them together.
Close with a one-line *Bottom line:* if it helps.

No preamble, no sign-off — start at the title line. Verify catalysts + pick good links with your tools."""


def _fmt_mover(s: MoverScore, held_wt: float, headlines: List[Dict[str, str]]) -> str:
    book = f"HELD {held_wt*100:.0f}% of book" if held_wt > 0 else "watchlist"
    unexp = " ❓" if s.tier == "UNEXPLAINED" else ""
    lines = [
        f"### {ball(s.move_pct)}{unexp} {s.ticker}  [{s.tier}]",
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
    intro = (
        f"Write Schyler's Crack-a-Dawn pre-market briefing for {date_str}.\n\n"
        f"MARKET CONTEXT: {market_context}\n\n"
        "These names were flagged by the Attention Score (already ranked; sigma = move vs the "
        "stock's own volatility, residual = move after stripping market/beta). Research WHY each "
        "moved overnight and write it up:\n\n"
        f"{movers}\n"
    )
    return intro + _OUTPUT_TEMPLATE


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
    """Trim any pre-brief preamble — start at the title line (the 🌅 line, or a #/* header)."""
    out = (out or "").strip()
    if not out:
        return None
    lines = out.splitlines()
    for i, line in enumerate(lines):
        s = line.lstrip()
        if "🌅" in line or s.startswith("#") or s.startswith("*🌅"):
            return "\n".join(lines[i:]).strip()
    return out
