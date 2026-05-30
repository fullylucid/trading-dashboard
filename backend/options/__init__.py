"""
Options Strategist backend package.

Deterministic, Python-side options analytics that feed the client-side
strategy engine and the Claude (WSL2) opportunity finder:

  - bs.py         Black-Scholes pricing, Greeks, implied-vol solver, expected move
  - chains.py     yfinance option-chain snapshots (spot, ATM IV, expirations, liquidity)
  - discovery.py  universe assembly (portfolio + watchlist + market scan) + the
                  structured snapshot/prompt handed to Claude

The strategy payoff/Greeks lab itself lives in the frontend; this package
supplies the live market inputs and the deterministic opportunity snapshot.
"""

from . import bs  # noqa: F401

__all__ = ["bs"]
