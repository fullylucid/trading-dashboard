"""Catalyst pressure BY SECTOR — earnings clustering + economic-release impact.

This module answers a single question for the rotation engine: *which sectors
have the heaviest near-term catalyst load*, where a "catalyst" is either

1. **Earnings-season clustering** — many (and large) constituent companies of a
   sector reporting earnings in the next few trading days. A sector reporting a
   cluster of mega-caps this week is primed for an outsized, news-driven move
   (post-earnings drift, sympathy moves across the sector). Source: the Finnhub
   ``/calendar/earnings`` endpoint, aggregated per GICS sector.
2. **Economic-release impact** — a scheduled / just-released macro print (CPI,
   payrolls, Fed funds, 10Y yield, ISM, ...) that maps, with a *sign*, onto the
   sectors it historically moves. E.g. a hot CPI is hawkish: a tailwind for
   Financials (rates up) and a headwind for rate-sensitive Utilities / REITs.
   Source: FRED (env ``FRED_API_KEY``, optional), via a curated series->sector
   sensitivity map.

Layering (mirrors ``backend/analytics/`` and the rest of ``sector_rotation/``):

- **PURE scoring** — :func:`aggregate_earnings_by_sector`,
  :func:`score_earnings_clustering`, :func:`map_econ_release_to_sectors`,
  :func:`score_catalyst_pressure`. numpy/pandas/stdlib only, data passed IN,
  deterministic, fully unit-tested. No clock, no network, no disk.
- **IO functions** — :func:`fetch_earnings_calendar` (Finnhub) and
  :func:`fetch_fred_latest` / :func:`fetch_econ_releases` (FRED). The ONLY
  network-touching code. Each sends a descriptive ``User-Agent``, applies a
  timeout, is fully exception-wrapped, and **degrades to empty / ``None`` —
  it never raises into the caller.** FRED is entirely optional (no key -> {}).

Contracts (the shape PURE consumes / IO produces)
--------------------------------------------------
*Earnings event dict* (what :func:`fetch_earnings_calendar` yields and
:func:`aggregate_earnings_by_sector` consumes)::

    {
        "symbol":       "JPM",          # constituent ticker (uppercased)
        "date":         "2026-05-12",   # report date, YYYY-MM-DD
        "hour":         "bmo",          # bmo/amc/dmh (best-effort, optional)
        "eps_estimate": 4.10,           # consensus EPS estimate (optional)
        "eps_actual":   None,           # filled post-report (optional)
        "market_cap":   5.6e11,         # USD market cap if known (optional)
    }

*Econ-release dict* (what :func:`fetch_econ_releases` yields and
:func:`map_econ_release_to_sectors` consumes)::

    {
        "series_id": "CPIAUCSL",        # FRED series id
        "label":     "CPI",            # human label
        "date":      "2026-05-13",     # observation/release date, YYYY-MM-DD
        "value":     314.2,            # latest observed value
        "previous":  313.1,            # prior observation (for delta sign)
    }

Sources / references
--------------------
- Finnhub earnings calendar: https://finnhub.io/docs/api/earnings-calendar
  (free tier; ``FINNHUB_API_KEY``; ~60 calls/min).
- FRED API:                  https://fred.stlouisfed.org/docs/api/fred/
  (``FRED_API_KEY``; series/observations; ~120 req/min).
- Sector-rotation research spec (sections 4.1 Earnings Calendar, 4.2 Economic
  Data Calendar, 5.3 Fed Signals) — series->sector mapping and weighting.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sector_rotation.sectors import (
    SECTOR_TO_ETF,
    normalize_sector_name,
)

logger = logging.getLogger(__name__)

__all__ = [
    # PURE
    "aggregate_earnings_by_sector",
    "score_earnings_clustering",
    "map_econ_release_to_sectors",
    "score_catalyst_pressure",
    "ECON_SERIES",
    "ECON_SECTOR_MAP",
    "market_cap_weight",
    # IO
    "fetch_earnings_calendar",
    "fetch_fred_latest",
    "fetch_econ_releases",
]


# --------------------------------------------------------------------------- #
# Curated econ-series metadata (PURE constants).
#
# Each FRED series we track is mapped to the sectors it historically moves,
# with a per-sector SIGN encoding the *directional* sensitivity to a HOTTER /
# HIGHER-than-prior print:
#
#   +1  -> a higher/hotter print is a TAILWIND for the sector
#   -1  -> a higher/hotter print is a HEADWIND for the sector
#
# The PURE scorer multiplies this sign by the (signed) surprise/delta to get a
# per-sector econ catalyst contribution. Sector names are CANONICAL GICS names
# (keys of SECTOR_TO_ETF) so the map round-trips against the shared universe.
#
# Mapping rationale (from research spec sections 4.2 / 5.3):
#   CPI / PCE hot  -> hawkish: + Financials (rates), - Utilities/REITs (duration)
#   Fed funds up   -> + Financials, - Utilities/REITs/Discretionary (credit)
#   10Y yield up   -> + Financials, - Utilities/REITs
#   Payrolls hot   -> risk-on/cyclical: + Discretionary/Industrials/Energy/Fin,
#                                        - defensives Staples/Utilities
#   Unemployment up-> recessionary: + defensives (Staples/Utilities/HealthCare),
#                                    - cyclicals (Discretionary/Industrials/Fin)
#   ISM Mfg up     -> + Industrials/Materials/Energy
#   ISM Svc up     -> + Discretionary/Information Technology
#   VIX up         -> flight to safety: + defensives, - high-beta (Tech/Disc)
# --------------------------------------------------------------------------- #

#: FRED series ids we know how to track, with a human label.
ECON_SERIES: Dict[str, str] = {
    "CPIAUCSL": "CPI",
    "PCEPI": "PCE Inflation",
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Non-Farm Payrolls",
    "FEDFUNDS": "Fed Funds Rate",
    "DGS10": "10Y Treasury Yield",
    "VIXCLS": "VIX",
}

#: series_id -> { canonical GICS sector : sign (+1 tailwind / -1 headwind) }
#: for a HOTTER/HIGHER-than-prior print. Only sectors with a meaningful,
#: well-documented sensitivity are listed; unlisted sectors get 0 implicitly.
ECON_SECTOR_MAP: Dict[str, Dict[str, int]] = {
    "CPIAUCSL": {  # hot inflation -> hawkish
        "Financials": +1,
        "Energy": +1,
        "Utilities": -1,
        "Real Estate": -1,
        "Information Technology": -1,
    },
    "PCEPI": {
        "Financials": +1,
        "Utilities": -1,
        "Real Estate": -1,
        "Consumer Discretionary": -1,
    },
    "UNRATE": {  # rising unemployment -> recessionary, defensive rotation
        "Consumer Staples": +1,
        "Utilities": +1,
        "Health Care": +1,
        "Consumer Discretionary": -1,
        "Industrials": -1,
        "Financials": -1,
    },
    "PAYEMS": {  # strong payrolls -> risk-on / cyclical
        "Consumer Discretionary": +1,
        "Industrials": +1,
        "Energy": +1,
        "Financials": +1,
        "Consumer Staples": -1,
        "Utilities": -1,
    },
    "FEDFUNDS": {  # higher policy rate
        "Financials": +1,
        "Utilities": -1,
        "Real Estate": -1,
        "Consumer Discretionary": -1,
    },
    "DGS10": {  # higher long rates
        "Financials": +1,
        "Utilities": -1,
        "Real Estate": -1,
    },
    "VIXCLS": {  # spiking vol -> flight to safety
        "Consumer Staples": +1,
        "Utilities": +1,
        "Health Care": +1,
        "Information Technology": -1,
        "Consumer Discretionary": -1,
    },
}


# --------------------------------------------------------------------------- #
# Small tolerant coercion helpers (PURE).
# --------------------------------------------------------------------------- #
def _num(value: Any) -> Optional[float]:
    """Tolerant float coercion. ``None`` for missing/non-numeric/sentinel.

    FRED uses the string ``"."`` for a missing observation; treat it as None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if s == "" or s == ".":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def market_cap_weight(market_cap: Any) -> int:
    """PURE: map a market cap (USD) to an earnings importance weight.

    Mirrors the research spec's tiering — a mega-cap reporting carries far more
    sector-moving weight than a small-cap:

    - market cap > $1T            -> 3  (mega-cap)
    - $300B .. $1T                -> 2  (large-cap)
    - anything else / unknown     -> 1  (mid/small, or cap not provided)

    A missing/garbage cap conservatively counts as 1 (it still reports), never 0,
    so an event is never silently dropped from the count.
    """
    cap = _num(market_cap)
    if cap is None:
        return 1
    if cap > 1_000_000_000_000:
        return 3
    if cap >= 300_000_000_000:
        return 2
    return 1


# --------------------------------------------------------------------------- #
# PURE: earnings clustering by sector.
# --------------------------------------------------------------------------- #
def aggregate_earnings_by_sector(
    events: Iterable[Dict[str, Any]],
    ticker_to_sector: Dict[str, Optional[str]],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate upcoming earnings events into per-sector clustering stats.

    Each event is mapped to a GICS sector via ``ticker_to_sector`` (the caller
    resolves tickers->sectors out of band, e.g. via
    :func:`sector_rotation.sectors.sector_for_ticker`, so this function stays
    PURE). Events whose ticker has no sector mapping are dropped (they cannot be
    attributed to a sector's catalyst load).

    Parameters
    ----------
    events : iterable of dict
        Earnings event dicts (see module docstring). Only ``symbol`` and an
        optional ``market_cap`` are used here.
    ticker_to_sector : dict
        ``{TICKER -> canonical GICS sector | None}``. Lookups are
        case-insensitive on the ticker; a ``None`` value or a missing key both
        cause the event to be dropped. Vendor sector spellings are normalized.

    Returns
    -------
    dict
        ``{ canonical_sector : {
                "count":          int,    # number of reporting companies
                "weighted_count": float,  # sum of market_cap_weight() weights
                "symbols":        [..],   # sorted, de-duplicated tickers
                "etf":            "XLF",  # the SPDR proxy for the sector
        } }``

        Only sectors with at least one attributable event appear. Pure and
        deterministic; the inputs are not mutated.
    """
    # Normalize the ticker->sector map once (case-insensitive keys, canonical
    # sector values). Drop entries that don't resolve to a known sector.
    norm_map: Dict[str, str] = {}
    for tk, sec in (ticker_to_sector or {}).items():
        if not tk:
            continue
        canonical = normalize_sector_name(sec) if sec else None
        # normalize_sector_name returns None for already-canonical names only if
        # they're unknown; canonical names pass through, so this is safe.
        if canonical is None and sec in SECTOR_TO_ETF:
            canonical = sec
        if canonical is None:
            continue
        norm_map[str(tk).strip().upper()] = canonical

    agg: Dict[str, Dict[str, Any]] = {}
    seen: Dict[str, set] = defaultdict(set)  # sector -> set of symbols (de-dupe)

    for ev in events or []:
        sym = str((ev or {}).get("symbol") or "").strip().upper()
        if not sym:
            continue
        sector = norm_map.get(sym)
        if sector is None:
            continue  # unattributable -> not part of any sector's catalyst load
        if sym in seen[sector]:
            continue  # one company counts once even if it appears twice
        seen[sector].add(sym)

        bucket = agg.setdefault(
            sector,
            {
                "count": 0,
                "weighted_count": 0.0,
                "symbols": [],
                "etf": SECTOR_TO_ETF.get(sector, ""),
            },
        )
        bucket["count"] += 1
        bucket["weighted_count"] += float(market_cap_weight(ev.get("market_cap")))
        bucket["symbols"].append(sym)

    for sector, bucket in agg.items():
        bucket["symbols"] = sorted(set(bucket["symbols"]))

    return agg


def score_earnings_clustering(
    sector_agg: Dict[str, Dict[str, Any]],
    *,
    all_sectors: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Turn per-sector earnings aggregates into a 0..100 clustering score.

    A sector's earnings catalyst score reflects how heavy its reporting load is
    *relative to the other sectors this period*. We rank sectors by their
    ``weighted_count`` (mega-caps count more) and convert each sector's weight
    into a percentile-style score in ``[0, 100]``:

        score(sector) = 100 * weighted_count(sector) / max(weighted_count)

    so the busiest sector scores 100 and an empty sector scores 0. We also flag
    sectors above the 75th percentile of the *non-zero* weighted counts as in
    "earnings season" (the research spec's high-concentration trigger).

    Parameters
    ----------
    sector_agg : dict
        Output of :func:`aggregate_earnings_by_sector`.
    all_sectors : iterable of str, optional
        If given, sectors in this list with no events are included with a score
        of 0 (useful so the rotation engine sees every sector). Defaults to just
        the sectors present in ``sector_agg``.

    Returns
    -------
    dict
        ``{ sector : {
                "count":           int,
                "weighted_count":  float,
                "score":           float (0..100),
                "in_earnings_season": bool,
                "etf":             str,
        } }``

    Pure and deterministic. With no events at all, every score is 0 and no
    sector is flagged.
    """
    sectors: List[str] = list(all_sectors) if all_sectors is not None else list(sector_agg)
    # Ensure sectors present in the aggregate are included even if not in
    # all_sectors (defensive).
    for s in sector_agg:
        if s not in sectors:
            sectors.append(s)

    weighted = {
        s: float((sector_agg.get(s) or {}).get("weighted_count", 0.0) or 0.0)
        for s in sectors
    }
    max_w = max(weighted.values()) if weighted else 0.0

    # 75th percentile of the NON-ZERO weighted counts (numpy if available; a
    # stdlib fallback keeps the pure surface dependency-light for tests).
    nonzero = sorted(w for w in weighted.values() if w > 0.0)
    p75 = _percentile(nonzero, 75.0) if nonzero else 0.0

    out: Dict[str, Dict[str, Any]] = {}
    for s in sectors:
        w = weighted[s]
        agg = sector_agg.get(s) or {}
        score = (100.0 * w / max_w) if max_w > 0.0 else 0.0
        out[s] = {
            "count": int(agg.get("count", 0) or 0),
            "weighted_count": w,
            "score": float(round(score, 4)),
            # Strictly heaviest-tail: above the 75th pct AND actually reporting.
            "in_earnings_season": bool(w > 0.0 and w >= p75 and len(nonzero) >= 2),
            "etf": agg.get("etf") or SECTOR_TO_ETF.get(s, ""),
        }
    return out


def _percentile(sorted_vals: List[float], pct: float) -> float:
    """Linear-interpolation percentile on an ALREADY-SORTED list (PURE).

    Avoids a hard numpy dependency in the pure layer (numpy is available in the
    backend but the math is trivial and this keeps the helper testable in any
    env). Matches numpy's default ``linear`` interpolation.
    """
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac)


# --------------------------------------------------------------------------- #
# PURE: economic-release -> sector impact mapping.
# --------------------------------------------------------------------------- #
def map_econ_release_to_sectors(
    release: Dict[str, Any],
    *,
    clamp: float = 30.0,
) -> Dict[str, float]:
    """Map a single econ release to signed per-sector impact scores.

    The release's *surprise* is approximated by the percent change of the latest
    value vs. the previous observation (we have no live consensus feed; the
    prior print is the cheapest, look-ahead-free baseline). That signed surprise
    is multiplied by each sector's sensitivity sign from :data:`ECON_SECTOR_MAP`
    and scaled into a bounded per-sector contribution in ``[-clamp, +clamp]``.

        surprise_pct       = 100 * (value - previous) / |previous|
        impact(sector)     = clamp_to([-clamp, clamp],  sign * surprise_pct * k)

    For series quoted in *level* terms where a small absolute move is large
    (DGS10, FEDFUNDS, VIXCLS, UNRATE), an absolute-change basis is used instead
    of percent so e.g. a 25bp move in the 10Y registers meaningfully.

    Parameters
    ----------
    release : dict
        An econ-release dict (see module docstring). Requires ``series_id`` and
        a numeric ``value``; ``previous`` is used for the sign/magnitude. A
        release for an unknown series, or with no usable delta, yields ``{}``.
    clamp : float, default 30.0
        Symmetric bound on each per-sector impact (the research spec sizes the
        econ catalyst contribution around +/-20..30).

    Returns
    -------
    dict
        ``{ canonical_sector : signed_impact_float }`` for the sectors this
        series moves (others omitted). Empty dict if the series is unknown or
        the surprise cannot be computed. Pure and deterministic.
    """
    series_id = str((release or {}).get("series_id") or "").strip()
    sector_signs = ECON_SECTOR_MAP.get(series_id)
    if not sector_signs:
        return {}

    value = _num((release or {}).get("value"))
    prev = _num((release or {}).get("previous"))
    if value is None or prev is None:
        return {}

    # Level-quoted rate/vol series: use absolute change scaled up; for these a
    # 1.0 absolute move (e.g. +1% on the 10Y, +1pt unemployment) is a big deal.
    LEVEL_SERIES = {"DGS10", "FEDFUNDS", "VIXCLS", "UNRATE"}
    if series_id in LEVEL_SERIES:
        delta = value - prev
        # Scale: ~+/-1.0 absolute move -> near the clamp.
        surprise = delta * 30.0
    else:
        if prev == 0.0:
            return {}
        surprise = 100.0 * (value - prev) / abs(prev)
        surprise *= 8.0  # a ~0.4% MoM CPI surprise -> ~+3.2 before sign/scale

    out: Dict[str, float] = {}
    for sector, sign in sector_signs.items():
        raw = float(sign) * surprise
        out[sector] = float(round(max(-clamp, min(clamp, raw)), 4))
    return out


# --------------------------------------------------------------------------- #
# PURE: combine earnings + econ into one catalyst-pressure score per sector.
# --------------------------------------------------------------------------- #
def score_catalyst_pressure(
    earnings_scores: Optional[Dict[str, Dict[str, Any]]] = None,
    econ_releases: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    earnings_weight: float = 0.6,
    econ_weight: float = 0.4,
) -> Dict[str, Dict[str, Any]]:
    """Fuse earnings clustering + econ-release impact into per-sector catalyst.

    Produces the catalyst dimension the rotation engine consumes (research spec
    section 6.1 sizes it ``earnings*0.6 + econ*0.4``). The two inputs live on
    different scales by design and are normalized here:

    - Earnings clustering is a **non-directional tailwind**: a heavy reporting
      week is added catalyst (potential post-earnings drift / sympathy moves)
      but does not on its own say up or down, so the ``0..100`` clustering score
      maps to a ``0..+50`` contribution — quiet = neutral 0, never a penalty.
      This keeps a sector that only surfaces via an econ release from being
      spuriously dragged negative just because it has no earnings this week.
    - Econ impact is already signed and bounded (sum across all releases that
      touch the sector, then clamped to ``-50..+50``).

    The combined ``catalyst_score`` is a signed value in roughly ``[-50, +50]``
    where positive = net tailwind, negative = net headwind. A separate
    ``pressure`` magnitude (``0..100``, ``abs`` of the components pre-sign) is
    also returned so the engine can distinguish "high catalyst load, direction
    unclear" from "quiet".

    Parameters
    ----------
    earnings_scores : dict, optional
        Output of :func:`score_earnings_clustering` (per-sector). Optional.
    econ_releases : iterable of dict, optional
        Econ-release dicts; each is run through
        :func:`map_econ_release_to_sectors` and summed per sector. Optional.
    earnings_weight, econ_weight : float
        Blend weights (defaults 0.6 / 0.4 per the spec). Need not sum to 1.

    Returns
    -------
    dict
        ``{ sector : {
                "catalyst_score":  float,   # signed, ~[-50, +50]
                "pressure":        float,   # magnitude 0..100
                "earnings_score":  float,   # 0..100 passthrough
                "econ_impact":     float,   # signed sum of econ contributions
                "in_earnings_season": bool,
                "etf":             str,
        } }``

    Pure and deterministic. Sectors are the union of those appearing in either
    input; with both inputs empty, returns ``{}``.
    """
    earnings_scores = earnings_scores or {}

    # Sum econ impacts per sector across all releases.
    econ_impact: Dict[str, float] = defaultdict(float)
    for rel in econ_releases or []:
        for sector, impact in map_econ_release_to_sectors(rel).items():
            econ_impact[sector] += impact

    sectors = set(earnings_scores) | set(econ_impact)
    out: Dict[str, Dict[str, Any]] = {}
    for sector in sectors:
        es = earnings_scores.get(sector) or {}
        e_score = float(es.get("score", 0.0) or 0.0)          # 0..100
        # Non-directional tailwind: 0..100 -> 0..+50, neutral (not negative) when
        # the sector has no reporting this week.
        e_contrib = e_score * 0.5                             # 0..+50
        ec = float(max(-50.0, min(50.0, econ_impact.get(sector, 0.0))))

        catalyst_score = earnings_weight * e_contrib + econ_weight * ec
        # Pressure = how much catalyst is in play regardless of direction.
        pressure = min(100.0, abs(earnings_weight * e_score) + abs(econ_weight * ec) * 2.0)

        out[sector] = {
            "catalyst_score": float(round(catalyst_score, 4)),
            "pressure": float(round(pressure, 4)),
            "earnings_score": float(round(e_score, 4)),
            "econ_impact": float(round(econ_impact.get(sector, 0.0), 4)),
            "in_earnings_season": bool(es.get("in_earnings_season", False)),
            "etf": es.get("etf") or SECTOR_TO_ETF.get(sector, ""),
        }
    return out


# =========================================================================== #
# IO LAYER — the ONLY network-touching code. Never raises; degrades to empty.
# =========================================================================== #
_DEFAULT_USER_AGENT = (
    "Tradeskeebot/1.0 (trading-dashboard; contact: schylermcnally@gmail.com)"
)
_FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"
_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
_REQUEST_TIMEOUT = 10.0   # seconds
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5       # seconds; exponential
_THROTTLE = 0.12          # polite spacing between requests


def _user_agent() -> str:
    """Descriptive User-Agent from env, with a sensible fallback."""
    return os.environ.get("TRADESKEEBOT_USER_AGENT", "").strip() or _DEFAULT_USER_AGENT


def _http_get_json(
    url: str, params: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Optional[dict]:
    """GET JSON with retries/backoff. Returns parsed dict or ``None``.

    Never raises: a missing ``requests`` dependency, rate limits, transient 5xx,
    timeouts, and bad JSON all degrade to ``None``.
    """
    try:
        import requests  # local import keeps the pure surface import-light
    except Exception as e:  # pragma: no cover - requests is a backend dep
        logger.warning("catalyst: requests unavailable: %s", e)
        return None

    hdrs = {"User-Agent": _user_agent(), "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.info(
                    "catalyst: HTTP %s from %s, backoff %.1fs (attempt %d)",
                    resp.status_code, url, wait, attempt + 1,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 - tolerant by contract
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.info(
                "catalyst: request error (%s) for %s, backoff %.1fs (attempt %d)",
                e, url, wait, attempt + 1,
            )
            time.sleep(wait)
    return None


def fetch_earnings_calendar(
    days_ahead: int = 5,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """IO: fetch the upcoming earnings calendar from Finnhub.

    Hits ``/calendar/earnings`` for a forward window (default: today through
    ``days_ahead`` calendar days) and returns a flat list of **earnings event
    dicts** in the shape :func:`aggregate_earnings_by_sector` consumes. The
    window is forward-looking by construction, so there is no look-ahead concern
    — we only ever score catalysts that have *not yet happened*.

    Requires ``FINNHUB_API_KEY`` in the environment. **Never raises**: a missing
    key, missing ``requests``, network errors, rate limits, or unexpected
    payloads all degrade to ``[]``.

    Parameters
    ----------
    days_ahead : int, default 5
        Forward window size in calendar days (used when ``from_date`` /
        ``to_date`` are not given).
    from_date, to_date : str, optional
        Explicit ``YYYY-MM-DD`` bounds; override ``days_ahead`` when provided.

    Returns
    -------
    list of dict
        Earnings event dicts, or ``[]`` on any failure.
    """
    try:
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            logger.info("catalyst.fetch_earnings_calendar: FINNHUB_API_KEY not set")
            return []

        if from_date and to_date:
            start_s, end_s = from_date, to_date
        else:
            days_ahead = max(1, int(days_ahead))
            start = datetime.now(timezone.utc).date()
            end = start + timedelta(days=days_ahead)
            start_s, end_s = start.isoformat(), end.isoformat()

        time.sleep(_THROTTLE)
        data = _http_get_json(
            _FINNHUB_EARNINGS_URL,
            {"from": start_s, "to": end_s, "token": api_key},
        )
        if not data:
            return []

        raw = (data.get("earningsCalendar") if isinstance(data, dict) else None) or []
        if not isinstance(raw, list):
            return []

        out: List[Dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            out.append(
                {
                    "symbol": sym,
                    "date": str(row.get("date") or "").strip(),
                    "hour": str(row.get("hour") or "").strip().lower(),
                    "eps_estimate": _num(row.get("epsEstimate")),
                    "eps_actual": _num(row.get("epsActual")),
                    "revenue_estimate": _num(row.get("revenueEstimate")),
                    # Finnhub's calendar does not carry market cap; left None so
                    # market_cap_weight() treats it as a 1x (mid/small) report
                    # unless the caller enriches it.
                    "market_cap": _num(row.get("marketCapitalization")),
                }
            )
        return out
    except Exception as e:  # noqa: BLE001 - absolute top-level guard
        logger.warning("catalyst.fetch_earnings_calendar failed: %s", e)
        return []


def fetch_fred_latest(series_id: str, lookback_days: int = 120) -> Optional[Dict[str, Any]]:
    """IO: fetch the two most-recent observations of a FRED series.

    Returns an **econ-release dict** (``series_id``/``label``/``date``/``value``/
    ``previous``) built from the latest observation and the one before it, which
    is exactly what :func:`map_econ_release_to_sectors` needs for a delta. We
    request only completed observations within the lookback window and take the
    last two non-missing points (FRED encodes a missing value as ``"."``).

    FRED is **optional**: with no ``FRED_API_KEY`` the function returns ``None``
    immediately (the whole econ dimension simply degrades to empty downstream).
    **Never raises** — missing key/deps, network errors, or thin data all yield
    ``None``.

    Parameters
    ----------
    series_id : str
        A FRED series id (e.g. ``"CPIAUCSL"``).
    lookback_days : int, default 120
        How far back to look for the latest two observations.

    Returns
    -------
    dict | None
        Econ-release dict, or ``None`` if unavailable.
    """
    try:
        sid = str(series_id or "").strip()
        if not sid:
            return None
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        if not api_key:
            logger.info("catalyst.fetch_fred_latest: FRED_API_KEY not set (optional)")
            return None

        lookback_days = max(1, int(lookback_days))
        start = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()

        time.sleep(_THROTTLE)
        data = _http_get_json(
            _FRED_OBS_URL,
            {
                "series_id": sid,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start,
                "sort_order": "asc",
            },
        )
        if not data or not isinstance(data, dict):
            return None

        obs = data.get("observations") or []
        if not isinstance(obs, list):
            return None

        # Keep only completed, numeric observations in chronological order.
        clean = [
            (str(o.get("date") or "").strip(), _num(o.get("value")))
            for o in obs
            if isinstance(o, dict)
        ]
        clean = [(d, v) for (d, v) in clean if d and v is not None]
        if not clean:
            return None

        last_date, last_val = clean[-1]
        prev_val = clean[-2][1] if len(clean) >= 2 else None
        return {
            "series_id": sid,
            "label": ECON_SERIES.get(sid, sid),
            "date": last_date,
            "value": last_val,
            "previous": prev_val,
        }
    except Exception as e:  # noqa: BLE001 - absolute top-level guard
        logger.warning("catalyst.fetch_fred_latest(%s) failed: %s", series_id, e)
        return None


def fetch_econ_releases(
    series_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """IO: fetch latest econ-release dicts for the tracked FRED series.

    Convenience wrapper that calls :func:`fetch_fred_latest` for each series in
    ``series_ids`` (default: all keys of :data:`ECON_SERIES`) and returns the
    successful ones. The result feeds straight into :func:`score_catalyst_pressure`
    (or :func:`map_econ_release_to_sectors`). **Never raises**; returns ``[]``
    when FRED is unavailable (no key), so the econ dimension cleanly drops out.

    Parameters
    ----------
    series_ids : iterable of str, optional
        FRED series ids to fetch. Defaults to every series in
        :data:`ECON_SERIES`.

    Returns
    -------
    list of dict
        Econ-release dicts (one per series that resolved), possibly empty.
    """
    try:
        ids = list(series_ids) if series_ids is not None else list(ECON_SERIES)
        out: List[Dict[str, Any]] = []
        for sid in ids:
            rel = fetch_fred_latest(sid)
            if rel is not None:
                out.append(rel)
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("catalyst.fetch_econ_releases failed: %s", e)
        return []
