"""
2Chainz — scheduled open/close portfolio snapshot (zero-token).

    python -m twochainz.report --session open|close

Pulls the live book + day P&L and pushes a clean snapshot to @Siiigggbot. Cheap,
reliable, no LLM — 2Chainz the strategist (the chat) is the Opus part, on demand.
Trading-day gated (reuses Crack-a-Dawn's market calendar).
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging

from . import portfolio
from crack_a_dawn.market_calendar import is_trading_day
from crack_a_dawn import notify  # same @Siiigggbot sender

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("twochainz.report")

HEADERS = {
    "open": "🔔 Market Open — your book",
    "close": "🔔 Market Close — your book (final)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", choices=["open", "close"], required=True)
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    today = dt.date.today()
    if not args.force and not is_trading_day(today):
        logger.info("non-trading day — no %s snapshot", args.session)
        return 0

    snap = portfolio.snapshot()
    if not snap["holdings"]:
        logger.warning("empty book / fetch failed")
        if not args.no_send:
            notify.send(f"{HEADERS[args.session]}\n(book unavailable right now)")
        return 1

    text = portfolio.format_text(snap, HEADERS[args.session])
    if args.no_send:
        print(text)
    else:
        notify.send(text)
        logger.info("%s snapshot sent (%d holdings)", args.session, len(snap["holdings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
