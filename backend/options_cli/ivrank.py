"""
IV-rank / IV-percentile — the engine's missing primitive.

yfinance gives per-strike implied vol *now* but no IV history, and history can't
be fetched retroactively — so we accrue our own: a daily snapshot of the ~30-DTE
ATM IV per symbol (see ``scripts/snapshot_iv_history.py``), appended to a small
on-disk JSON store. Rank and percentile are then computed against that trailing
series:

    iv_rank       = (IV_now - min(window)) / (max(window) - min(window)),  clamped to [0, 1]
    iv_percentile = fraction of trailing days with IV <= IV_now

HONEST COLD-START: until the store holds ``min_obs`` trading days for a symbol,
``compute_metrics`` returns ``sufficient: False`` with ``iv_rank``/``iv_percentile``
as ``None`` — never a rank derived from a too-thin window.

No look-ahead: ranking for a given day only ever sees entries strictly *before*
that day (``IVHistoryStore.series(before=...)``); the store records at most one
entry per (symbol, calendar date) and rejects weekend dates (no completed bar).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import tempfile
from typing import Any, Dict, List, Optional

from .chains import Chain

logger = logging.getLogger("options_cli.ivrank")

WINDOW_DAYS = 252   # trailing window (trading days ~ 1y)
MIN_OBS = 60        # observations required before rank/percentile are trusted
MIN_VALID_IV = 0.01  # yfinance puts ~1e-5 garbage IV on dead quotes; ignore those


# --------------------------------------------------------------------------- #
# ATM IV extraction (pure — operates on an already-fetched Chain)
# --------------------------------------------------------------------------- #
def atm_iv(chain: Chain, exp: str) -> Optional[float]:
    """The at-the-money IV for one expiration: call + put IV at the strike nearest
    spot, averaged (one side alone if the other has no usable IV). None if neither
    side has a valid IV — never a garbage number."""
    if not chain.spot or chain.spot <= 0:
        return None
    ivs: List[float] = []
    for kind in ("call", "put"):
        legs = [c for c in chain.for_exp(exp, kind) if c.iv >= MIN_VALID_IV]
        if legs:
            ivs.append(min(legs, key=lambda c: abs(c.strike - chain.spot)).iv)
    return round(sum(ivs) / len(ivs), 6) if ivs else None


# --------------------------------------------------------------------------- #
# Rank / percentile math (pure)
# --------------------------------------------------------------------------- #
def iv_rank(past_ivs: List[float], iv_now: float) -> Optional[float]:
    """(IV_now - min) / (max - min) over the series, clamped to [0, 1].
    None on an empty or flat series (rank is undefined, not 0 or 1)."""
    if not past_ivs:
        return None
    lo, hi = min(past_ivs), max(past_ivs)
    if hi <= lo:
        return None
    return max(0.0, min(1.0, (iv_now - lo) / (hi - lo)))


def iv_percentile(past_ivs: List[float], iv_now: float) -> Optional[float]:
    """Fraction of trailing days with IV <= IV_now. None on an empty series."""
    if not past_ivs:
        return None
    return sum(1 for v in past_ivs if v <= iv_now) / len(past_ivs)


def compute_metrics(past_ivs: List[float], iv_now: float,
                    window: int = WINDOW_DAYS, min_obs: int = MIN_OBS) -> Dict[str, Any]:
    """Rank + percentile of ``iv_now`` against the last ``window`` values of
    ``past_ivs`` (which must already exclude the current day — no look-ahead is
    the caller's contract, enforced by ``IVHistoryStore.series(before=...)``).

    Cold-start honesty: with fewer than ``min_obs`` observations the metrics are
    ``None`` and ``sufficient`` is False — a rank off a 5-day window is noise."""
    windowed = past_ivs[-window:] if window > 0 else list(past_ivs)
    n = len(windowed)
    out: Dict[str, Any] = {
        "iv_now": round(iv_now, 6),
        "n_days": n,
        "window": window,
        "sufficient": n >= min_obs,
    }
    if not out["sufficient"]:
        out.update(iv_rank=None, iv_percentile=None, reason="insufficient_history")
        return out
    r = iv_rank(windowed, iv_now)
    p = iv_percentile(windowed, iv_now)
    out["iv_rank"] = round(r, 4) if r is not None else None
    out["iv_percentile"] = round(p, 4) if p is not None else None
    return out


# --------------------------------------------------------------------------- #
# History store — one small JSON file, atomic writes, tolerant reads
# --------------------------------------------------------------------------- #
def default_history_path() -> str:
    return os.environ.get(
        "IV_HISTORY_PATH",
        os.path.expanduser("~/.hermes/workspace/trading-dashboard/data/iv_history.json"),
    )


class IVHistoryStore:
    """Daily ATM-IV series per symbol. At most one entry per (symbol, date);
    re-recording the same date overwrites it (idempotent cron re-runs — last
    completed-day value wins). Weekend dates are rejected: no completed bar."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or default_history_path()

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("symbols"), dict):
                return data
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("iv history unreadable (%s); starting fresh in memory", e)
        return {"version": 1, "symbols": {}}

    def _save(self, data: Dict[str, Any]) -> bool:
        try:
            parent = os.path.dirname(self.path) or "."
            os.makedirs(parent, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".iv_history.", suffix=".json", dir=parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, sort_keys=True)
                os.replace(tmp, self.path)
                return True
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:  # noqa: BLE001
            logger.warning("iv history write failed: %s", e)
            return False

    def record(self, symbol: str, date: dt.date, iv: float,
               spot: Optional[float] = None, expiration: Optional[str] = None,
               dte: Optional[int] = None) -> bool:
        """Append/overwrite one day's ATM IV. Returns False (and records nothing)
        for invalid IV or a weekend date."""
        if not (isinstance(iv, (int, float)) and math.isfinite(iv) and iv >= MIN_VALID_IV):
            logger.warning("refusing to record invalid iv=%r for %s", iv, symbol)
            return False
        if date.weekday() >= 5:
            logger.info("skipping weekend date %s for %s (no completed bar)", date, symbol)
            return False
        data = self._load()
        entry: Dict[str, Any] = {"iv": round(float(iv), 6)}
        if spot is not None:
            entry["spot"] = round(float(spot), 4)
        if expiration:
            entry["expiration"] = expiration
        if dte is not None:
            entry["dte"] = int(dte)
        data["symbols"].setdefault(symbol.upper(), {})[date.isoformat()] = entry
        return self._save(data)

    def series(self, symbol: str, before: Optional[dt.date] = None,
               window: Optional[int] = None) -> List[Dict[str, Any]]:
        """The symbol's daily entries sorted by date ascending, each with its
        ``date`` inlined. ``before`` keeps only entries strictly earlier than that
        date (the no-look-ahead guard); ``window`` keeps only the last N."""
        days = self._load()["symbols"].get(symbol.upper(), {})
        cutoff = before.isoformat() if before else None
        rows = [{"date": d, **e} for d, e in sorted(days.items())
                if cutoff is None or d < cutoff]
        return rows[-window:] if window else rows
