#!/usr/bin/env python3
"""Append today's ~30-DTE ATM implied vol per watchlist symbol to the IV history
store (box cron / systemd timer — zero tokens).

    python3 scripts/snapshot_iv_history.py [--watchlist SPY,QQQ,...] [--target-dte 30]

IV history cannot be fetched retroactively from yfinance, so every day this runs
is a day of history we keep forever; every day it doesn't is gone. Schedule it
once per trading day AFTER the US close (>= 16:15 ET / 13:15 PT) so the recorded
IV is from completed bars, not a mid-session read.

Guards (no look-ahead, no garbage):
- weekends: exits cleanly without recording (the store also rejects weekend dates);
- holidays: yfinance serves the prior session's chain — the recorded value
  duplicates the last trading day. Known minor noise, harmless to rank/percentile.
- per-symbol failures are logged and skipped; one bad ticker never aborts the run.

Exit code: 0 normally (including weekend no-op), 1 only when it is a weekday and
NOTHING could be recorded (hard failure worth alerting on).

Store path: $IV_HISTORY_PATH (default ~/.hermes/workspace/trading-dashboard/data/
iv_history.json). Watchlist: --watchlist > $IV_WATCHLIST > liquid default below.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

# Make the backend package importable whether invoked from repo root or scripts/.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("snapshot_iv_history")

# Liquid, options-heavy underlyings — names whose chains are dense enough that a
# 30-DTE ATM IV is always well-defined.
DEFAULT_WATCHLIST = "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watchlist", default=os.environ.get("IV_WATCHLIST", DEFAULT_WATCHLIST),
                    help="comma-separated symbols")
    ap.add_argument("--target-dte", type=int, default=30,
                    help="snapshot the expiration nearest this many days out")
    args = ap.parse_args()

    today = dt.date.today()
    if today.weekday() >= 5:
        logger.info("weekend (%s) — no completed bar to record; exiting cleanly", today)
        return 0

    from options_cli.chains import get_chain
    from options_cli.ivrank import IVHistoryStore, atm_iv

    symbols = [s.strip().upper() for s in args.watchlist.split(",") if s.strip()]
    store = IVHistoryStore()
    written = 0
    for sym in symbols:
        try:
            ch = get_chain(sym, target_dte=args.target_dte)
            if not ch.contracts:
                logger.warning("%s: no option chain; skipped", sym)
                continue
            exp = ch.contracts[0].expiration
            iv = atm_iv(ch, exp)
            if iv is None:
                logger.warning("%s: no usable ATM IV at %s; skipped", sym, exp)
                continue
            dte = ch.contracts[0].dte
            if store.record(sym, today, iv, spot=ch.spot, expiration=exp, dte=dte):
                written += 1
                logger.info("%s: iv=%.4f spot=%.2f exp=%s dte=%d", sym, iv, ch.spot, exp, dte)
        except Exception as e:  # noqa: BLE001 — one bad ticker never aborts the run
            logger.warning("%s: snapshot failed: %s", sym, e)

    logger.info("recorded %d/%d symbols -> %s", written, len(symbols), store.path)
    if symbols and written == 0:
        logger.error("nothing recorded on a weekday — hard failure")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
