"""
Trade execution — BUILT BUT HARD-DISABLED.

Two locks, both must be deliberately opened: the env flag OPTS_TRADING_ENABLED=true
AND an explicit per-order confirm. Even then this only PROPOSES — wiring the actual
SnapTrade place-order call is intentionally left as the final, separate step so it
can never fire by accident. Matches the dashboard's propose-then-confirm guardrail.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class OrderProposal:
    action: str       # BUY_TO_OPEN / SELL_TO_OPEN / ...
    contract: str     # OCC symbol or "SYM exp strike C/P"
    quantity: int
    limit: float
    note: str = ""

    def render(self) -> str:
        return (f"PROPOSED ORDER (not sent):\n"
                f"  {self.action}  {self.quantity}x  {self.contract}  @ ${self.limit:.2f} limit\n"
                f"  {self.note}")


def trading_enabled() -> bool:
    return os.getenv("OPTS_TRADING_ENABLED", "").strip().lower() in ("1", "true", "yes")


def submit(proposal: OrderProposal, confirm: bool = False) -> str:
    """Gate 1: env flag. Gate 2: explicit confirm. Gate 3: execution not wired (by design)."""
    if not trading_enabled():
        return (proposal.render() +
                "\n\n🔒 Trading DISABLED (set OPTS_TRADING_ENABLED=true to arm). Nothing sent.")
    if not confirm:
        return proposal.render() + "\n\n⚠️ Armed but unconfirmed. Re-run with --confirm to proceed."
    # Deliberately not wired: the SnapTrade place-order call is the final manual step.
    return (proposal.render() +
            "\n\n⛔ Execution path intentionally not connected yet — wire SnapTrade place-order "
            "as a separate, reviewed change before this can ever send a live order.")
