"""
Crack-a-Dawn P0 dry-run — eyeball the Attention Score on real tickers.

    python -m crack_a_dawn.dryrun AAPL NVDA AMD KO TSLA ...

No LLM, no catalyst lookup yet — just: gather -> score -> ranked tiers. On weekends/
off-hours the "move" is the latest realized daily move (the mechanism is identical;
only the data window differs from a live pre-market run).
"""
from __future__ import annotations

import sys
from typing import Dict, List

from .scoring import TIER_EMOJI, rank_movers
from .data import build_inputs

# A diverse default sample (mixed volatility + a semi cluster) if none passed.
DEFAULT_WATCH = ["AAPL", "MSFT", "NVDA", "AMD", "AVGO", "TSLA", "KO", "JNJ", "PLTR"]
DEFAULT_HELD: Dict[str, float] = {"NVDA": 0.18, "KO": 0.07}  # demo holdings + weights


def main(argv: List[str]) -> int:
    tickers = argv or DEFAULT_WATCH
    held = {} if argv else DEFAULT_HELD
    print(f"Crack-a-Dawn dry-run — {len(tickers)} names "
          f"(held: {', '.join(held) or 'none'})\n" + "=" * 78)
    rows = build_inputs(tickers, held=held)
    if not rows:
        print("No data fetched (network/yfinance issue).")
        return 1
    ranked = rank_movers(rows)
    print(f"{'':2} {'TKR':<6}{'MOVE':>7}{'σ':>7}{'resid':>8}{'RVOL':>6}"
          f"{'rel':>6}{'score':>7}  why")
    print("-" * 78)
    for s in ranked:
        rvol = f"{s.rvol:.1f}x" if s.rvol is not None else "  -"
        print(f"{TIER_EMOJI[s.tier]} {s.ticker:<6}{s.move_pct:>6.1f}%{s.sigma:>7.1f}"
              f"{s.residual_pct:>7.1f}%{rvol:>6}{s.relevance:>6.2f}{s.composite:>7.2f}"
              f"  {'; '.join(s.reasons[:3])}")
    print("=" * 78)
    lead = [s for s in ranked if s.tier in ("ACT", "UNEXPLAINED", "KNOW")]
    print(f"Lead: {len(lead)} name(s) would surface in the brief "
          f"({sum(s.tier=='ACT' for s in ranked)} ACT, "
          f"{sum(s.tier=='UNEXPLAINED' for s in ranked)} unexplained, "
          f"{sum(s.tier=='KNOW' for s in ranked)} know).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
