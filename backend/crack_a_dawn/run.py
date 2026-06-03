"""
Crack-a-Dawn — orchestrator. Runs as a dedicated box cron (systemd timer).

    python -m crack_a_dawn.run [--no-send] [--limit N] [--session premarket|midmorning]

universe -> Attention Score -> ground (headlines) -> Opus synthesis -> persist -> Telegram.
Always emits/sends *something* (incl. quiet/holiday/error) so silence means a failure.

Sessions: the 6 AM PT timer runs the default `premarket` brief; a second 7:30 AM PT
timer runs `--session midmorning` (the open + first-hour sweep). The session sets the
title, the move-window wording, and a brief-file suffix so the second run does NOT
overwrite the morning brief (and stays out of the date-indexed frontend archive).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from typing import List

from .scoring import MoverScore, rank_movers, TIER_ACT, TIER_KNOW, TIER_UNEXPLAINED, ball
from .data import build_inputs, _fetch_one
from .universe import get_universe
from .catalysts import ground
from .synthesize import build_prompt, synthesize
from .market_calendar import is_trading_day
from . import notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("crack_a_dawn.run")

BRIEFS_DIR = os.getenv("CRACKDAWN_BRIEFS_DIR", os.path.expanduser("~/.config/trading-dashboard/briefs"))
LEAD_TIERS = {TIER_ACT, TIER_UNEXPLAINED, TIER_KNOW}

# session -> (title label, move-window phrasing, brief-file suffix).
# premarket keeps the original behavior byte-for-byte (empty label/suffix).
SESSIONS = {
    "premarket": ("", "overnight", ""),
    "midmorning": ("Mid-Morning Sweep", "this morning since the open", "-midmorning"),
}


def _market_context() -> str:
    import yfinance as yf
    bits = []
    for sym, label in [("SPY", "S&P"), ("QQQ", "Nasdaq"), ("^VIX", "VIX")]:
        d = _fetch_one(yf, sym, prepost=True)
        if d:
            bits.append(f"{label} {d['move_pct']:+.1f}%" if sym != "^VIX"
                        else f"VIX {d['last']:.1f}")
    return ", ".join(bits) or "market data unavailable"


def _persist(date_str: str, brief_md: str, scored: List[MoverScore], suffix: str = "") -> str:
    os.makedirs(BRIEFS_DIR, exist_ok=True)
    md_path = os.path.join(BRIEFS_DIR, f"{date_str}{suffix}.md")
    with open(md_path, "w") as f:
        f.write(brief_md)
    with open(os.path.join(BRIEFS_DIR, f"{date_str}{suffix}.json"), "w") as f:
        json.dump({
            "date": date_str,
            "brief_markdown": brief_md,
            "movers": [{
                "ticker": s.ticker, "tier": s.tier, "move_pct": round(s.move_pct, 2),
                "sigma": round(s.sigma, 2), "residual_pct": round(s.residual_pct, 2),
                "rvol": round(s.rvol, 2) if s.rvol is not None else None,
                "composite": round(s.composite, 3), "reasons": s.reasons,
            } for s in scored],
        }, f, indent=2)
    return md_path


def _lead_excerpt(brief_md: str) -> str:
    # Telegram lean push = everything up to the first section after the Lead.
    for marker in ("\n## Sector", "\n## Per", "\n# Sector", "\n## Cluster"):
        i = brief_md.find(marker)
        if i > 0:
            return brief_md[:i].strip()
    return brief_md[:3500].strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-send", action="store_true", help="skip Telegram")
    ap.add_argument("--limit", type=int, default=8, help="max flagged names to synthesize")
    ap.add_argument("--force", action="store_true", help="run even on a non-trading day")
    ap.add_argument("--session", choices=sorted(SESSIONS), default="premarket",
                    help="premarket (6 AM brief) or midmorning (7:30 AM sweep)")
    args = ap.parse_args()

    label, move_window, suffix = SESSIONS[args.session]
    tag = f" {label}" if label else ""

    today = dt.date.today()
    date_str = today.isoformat()
    logger.info("Crack-a-Dawn run for %s (session=%s)", date_str, args.session)

    if not args.force and not is_trading_day(today):
        msg = f"🌅 Crack-a-Dawn{tag} — {date_str}: US market closed today (weekend/holiday). No brief."
        if not args.no_send:
            notify.send(msg)
        logger.info("non-trading day — skipping")
        return 0

    held, tickers = get_universe()
    if not tickers:
        msg = f"🌅 Crack-a-Dawn{tag} {date_str}: no universe (portfolio/watchlist empty or unreachable)."
        if not args.no_send:
            notify.send(msg)
        logger.warning(msg)
        return 1

    rows = build_inputs(tickers, held=held)
    scored = rank_movers(rows)

    flagged = [s for s in scored if s.tier in LEAD_TIERS][: args.limit]
    if not flagged:                      # quiet morning — still surface the single most-notable
        flagged = scored[:1]

    mkt = _market_context()
    grounding = ground([s.ticker for s in flagged], today=today)
    prompt = build_prompt(date_str, mkt, flagged, held, grounding, label=label, move_window=move_window)

    logger.info("synthesizing brief over %d flagged names…", len(flagged))
    brief = synthesize(prompt)
    if not brief:
        msg = (f"🌅 Crack-a-Dawn{tag} {date_str}: scoring ran ({len(flagged)} flagged) but synthesis "
               f"failed. Top: " + ", ".join(f"{ball(s.move_pct)}{s.ticker} {s.move_pct:+.1f}%"
                                             for s in flagged[:5]))
        if not args.no_send:
            notify.send(msg)
        logger.error("synthesis failed; sent fallback")
        return 2

    md_path = _persist(date_str, brief, scored, suffix)
    logger.info("brief saved -> %s", md_path)

    if not args.no_send:
        # The brief is now the full self-contained Telegram briefing (its own title +
        # market context), sized for one message — send it whole.
        notify.send(brief)
        logger.info("brief delivered to Telegram (%d chars)", len(brief))
    else:
        print("\n" + "=" * 80 + "\n" + brief + "\n" + "=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
