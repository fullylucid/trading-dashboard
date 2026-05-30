"""Sector-rotation intelligence (Phase 2.5).

Layering mirrors ``backend/analytics/``:

- **PURE constants / helpers** (numpy/pandas/stdlib only, no network, no disk,
  fully unit-testable): the SPDR sector-ETF <-> GICS universe in
  :mod:`sectors`, the per-stream math modules, and the fusion/mapping in
  :mod:`synthesis` (``fuse_rotation`` / ``map_to_companies``).
- **IO functions** (clearly marked, exception-wrapped, UA/rate-limit-compliant,
  degrade to empty / ``None`` and never raise): network-touching lookups such
  as :func:`sectors.sector_for_ticker` and the stream fetchers, plus the single
  orchestrator :func:`synthesis.run_sector_rotation`.

Public surface (assembled by the wiring phase)
----------------------------------------------
- :func:`run_sector_rotation` — the IO orchestrator (the dashboard / digest entry
  point): runs all 5 streams, fuses, maps to holdings, never raises.
- :func:`fuse_rotation` — PURE: fuse the 5 streams into a per-sector read.
- :func:`map_to_companies` — PURE-by-injection: tag holdings with their sector's
  rotation status (used additively per-ticker in the portfolio scan).
- Sector universe constants + lookups (:data:`SECTOR_ETFS`, :func:`sector_for_ticker`,
  …) so callers don't reach into submodules.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# --- Sector universe (PURE constants + the one IO lookup) ------------------- #
from sector_rotation.sectors import (  # noqa: E402
    BENCHMARK,
    SECTOR_ETFS,
    SECTOR_TO_ETF,
    ETF_TO_SECTOR,
    SECTOR_ETF_SYMBOLS,
    ALL_ROTATION_SYMBOLS,
    normalize_sector_name,
    etf_to_sector,
    sector_to_etf,
    is_sector_etf,
    sector_for_ticker,
)

# --- Synthesis: fusion + mapping + orchestrator ----------------------------- #
from sector_rotation.synthesis import (  # noqa: E402
    STREAM_WEIGHTS,
    CONF_ALERT,
    CONF_WATCH,
    SCORE_IN,
    SCORE_OUT,
    fuse_rotation,
    map_to_companies,
    run_sector_rotation,
)

__all__ = [
    # sector universe
    "BENCHMARK",
    "SECTOR_ETFS",
    "SECTOR_TO_ETF",
    "ETF_TO_SECTOR",
    "SECTOR_ETF_SYMBOLS",
    "ALL_ROTATION_SYMBOLS",
    "normalize_sector_name",
    "etf_to_sector",
    "sector_to_etf",
    "is_sector_etf",
    "sector_for_ticker",
    # synthesis
    "STREAM_WEIGHTS",
    "CONF_ALERT",
    "CONF_WATCH",
    "SCORE_IN",
    "SCORE_OUT",
    "fuse_rotation",
    "map_to_companies",
    "run_sector_rotation",
]
