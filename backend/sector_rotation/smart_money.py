"""Smart-money flow aggregated BY SECTOR (insider Form-4 clusters + optional 13F).

This module rolls the *issuer-level* insider signal produced by
``backend/analytics/insider`` up to the **sector** level so it can fuse with the
price/RRG backbone of the rotation scan. The strongest insider tell — several
distinct insiders of the same issuer buying open-market (code ``P``) inside a
short window, i.e. a *cluster* — is mapped to a GICS sector via
:func:`sector_rotation.sectors.sector_for_ticker` and aggregated into a single
per-sector "smart-money score".

Layering (mirrors ``backend/analytics/`` and ``sector_rotation/sectors``):

- **PURE aggregation** (no network, no disk, deterministic, unit-tested):
  :func:`aggregate_clusters_by_sector`, :func:`aggregate_13f_by_sector`,
  :func:`fuse_smart_money`. These take *already-fetched* objects IN — insider
  clusters (as produced by ``analytics.insider.cluster_buys``), each annotated
  with a ``sector`` key, and (optionally) 13F per-sector market-value snapshots —
  and return per-sector scores. They never touch the network.
- **IO functions** (clearly marked, exception-wrapped, degrade to ``{}``/``[]``,
  never raise): :func:`fetch_sector_insider_clusters` reuses
  ``analytics.insider.fetch_form4`` + ``cluster_buys`` for a universe of tickers
  and tags each cluster with its sector via ``sectors.sector_for_ticker``.

Why insider clusters drive the score
------------------------------------
Form-4 is filed within ~2 business days of the trade (~100% reliable, minimal
lag), and a *cluster* of distinct buyers is far less noisy than a lone purchase
(see ``analytics/insider`` and the sector-rotation research spec §2.2). We
deliberately reuse ``cluster_buys`` / ``score_insider_signal`` rather than
re-implement insider logic, so the per-issuer scoring stays in one place.

13F is **optional and explicitly flagged as lagging**
-----------------------------------------------------
13F institutional holdings are a quarter-end snapshot filed up to 45 days late,
so the data is routinely 60-90 days stale (research spec §2.3). It is therefore
*optional*, off by default, and every per-sector result it contributes is
stamped ``"lagging": True`` so downstream fusion/UI can de-weight or caption it.
It is never allowed to dominate the (timely) insider signal.

Sources / references
--------------------
- ``backend/analytics/insider``  — Form-4 fetch + cluster + per-issuer scoring.
- ``backend/sector_rotation/sectors`` — ticker -> GICS sector, 11 SPDR universe.
- Sector-rotation research spec §2.2 (insider Form-4) and §2.3 (13F lag).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

from analytics.insider import (
    cluster_buys,
    fetch_form4,
    score_insider_signal,
)

from .sectors import SECTOR_TO_ETF, normalize_sector_name, sector_for_ticker

logger = logging.getLogger(__name__)

__all__ = [
    "aggregate_clusters_by_sector",
    "aggregate_13f_by_sector",
    "fuse_smart_money",
    "fetch_sector_insider_clusters",
]


# --------------------------------------------------------------------------- #
# Helpers (pure)
# --------------------------------------------------------------------------- #
def _num(value: Any) -> float:
    """Tolerant float coercion; non-numeric / missing -> 0.0."""
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _cluster_sector(cluster: Mapping[str, Any]) -> Optional[str]:
    """Best-effort canonical GICS sector for a cluster.

    Prefers an explicit ``sector`` key (set by the IO layer when it resolves the
    cluster's issuer ticker), normalising it to canonical GICS spelling. Returns
    ``None`` if absent/unrecognised — such clusters are dropped from per-sector
    aggregation (we never guess). PURE: does NOT call the network resolver; the
    IO layer is responsible for populating ``sector``.
    """
    return normalize_sector_name(cluster.get("sector"))


# --------------------------------------------------------------------------- #
# PURE aggregation — insider clusters -> per-sector smart-money score
# --------------------------------------------------------------------------- #
def aggregate_clusters_by_sector(
    clusters: Iterable[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Roll insider-buy *clusters* up into a per-sector smart-money signal.

    Each input cluster is a dict as produced by
    ``analytics.insider.cluster_buys`` (``symbol``, ``num_insiders``,
    ``total_value``, ``filings`` ...), additionally annotated with a ``sector``
    key naming its issuer's GICS sector (the IO layer sets this via
    ``sectors.sector_for_ticker``). Clusters with no resolvable sector are
    skipped — we never attribute flow to a sector we cannot name.

    Per sector we sum each cluster's insider-signal *confidence* (from
    :func:`analytics.insider.score_insider_signal`, the single source of truth
    for per-issuer scoring) and surface the supporting counts so the score is
    explainable. The sector ``score`` is the summed confidence, **capped at
    100** so one frenzied sector cannot blow out the scale relative to others.

    PURE / deterministic — no network, no disk, no clock dependence.

    Parameters
    ----------
    clusters : iterable of mapping
        Insider clusters, each ideally carrying a ``sector`` key. Tolerant of
        missing keys; bad/sectorless clusters are dropped.

    Returns
    -------
    dict
        ``{canonical_sector: per_sector_dict}`` where each value is::

            {
                "sector":         "Information Technology",
                "etf":            "XLK",
                "score":          72.0,    # summed cluster confidence, 0..100
                "num_clusters":   2,
                "num_buys":       5,
                "num_insiders":   4,       # distinct insiders across clusters
                "total_value":    1_250_000.0,
                "symbols":        ["NVDA", "SMCI"],   # contributing issuers, sorted
                "source":         "insider_form4",
                "lagging":        False,
            }

        Sectors with no qualifying clusters are simply absent from the dict.
    """
    by_sector: Dict[str, Dict[str, Any]] = {}
    insiders_seen: Dict[str, set] = defaultdict(set)
    symbols_seen: Dict[str, set] = defaultdict(set)

    for cluster in clusters or []:
        sector = _cluster_sector(cluster)
        if sector is None:
            continue

        confidence = _num(score_insider_signal(dict(cluster)).get("confidence"))
        if confidence <= 0:
            # A non-cluster (scored 0) carries no smart-money weight.
            continue

        acc = by_sector.get(sector)
        if acc is None:
            acc = {
                "sector": sector,
                "etf": SECTOR_TO_ETF.get(sector),
                "score": 0.0,
                "num_clusters": 0,
                "num_buys": 0,
                "num_insiders": 0,
                "total_value": 0.0,
                "symbols": [],
                "source": "insider_form4",
                "lagging": False,
            }
            by_sector[sector] = acc

        acc["score"] += confidence
        acc["num_clusters"] += 1
        acc["num_buys"] += int(_num(cluster.get("num_buys")))
        acc["total_value"] += _num(cluster.get("total_value"))

        for name in cluster.get("insiders", []) or []:
            insiders_seen[sector].add(str(name).strip().upper())
        sym = str(cluster.get("symbol") or "").strip().upper()
        if sym:
            symbols_seen[sector].add(sym)

    for sector, acc in by_sector.items():
        acc["score"] = float(min(100.0, round(acc["score"], 2)))
        acc["total_value"] = float(round(acc["total_value"], 2))
        acc["num_insiders"] = len(insiders_seen[sector])
        acc["symbols"] = sorted(symbols_seen[sector])

    return by_sector


# --------------------------------------------------------------------------- #
# PURE aggregation — OPTIONAL, LAGGING: 13F per-sector market-value deltas
# --------------------------------------------------------------------------- #
def aggregate_13f_by_sector(
    mv_current: Mapping[str, float],
    mv_prior: Optional[Mapping[str, float]] = None,
    *,
    min_pct_flag: float = 0.05,
) -> Dict[str, Dict[str, Any]]:
    """Aggregate quarterly 13F institutional market value into per-sector flow.

    **Optional and LAGGING** (research spec §2.3): 13F is a quarter-end snapshot
    filed up to 45 days late, so this is routinely 60-90 days stale. Every
    returned row is stamped ``"lagging": True`` so fusion/UI can de-weight it; it
    must never override the (timely) insider signal.

    Given total institutional market value per sector for the current quarter
    (``mv_current``) and, optionally, the prior quarter (``mv_prior``), compute
    net flow and percent change per sector. Sector-name keys are normalised to
    canonical GICS spelling; unrecognised keys are dropped.

    PURE / deterministic — the *caller* (IO layer / sec-api) is responsible for
    having mapped individual 13F holdings to sectors and summed market value.

    Parameters
    ----------
    mv_current : mapping
        ``{sector: market_value}`` for the latest 13F quarter.
    mv_prior : mapping, optional
        ``{sector: market_value}`` for the prior quarter. If ``None``, only
        absolute levels are reported (flow/pct are ``None``).
    min_pct_flag : float, default 0.05
        Magnitude of ``pct_change`` (e.g. 0.05 = 5%) above which a sector is
        flagged ``inflow``/``outflow`` rather than ``flat``.

    Returns
    -------
    dict
        ``{canonical_sector: {...}}`` with ``sector``, ``etf``, ``mv_current``,
        ``mv_prior``, ``net_flow``, ``pct_change``, ``direction``
        (``inflow``/``outflow``/``flat``), ``source="13f_institutional"``,
        and ``lagging=True``.
    """
    out: Dict[str, Dict[str, Any]] = {}
    prior = mv_prior or {}

    # Normalise prior keys once so lookups below are canonical.
    prior_norm: Dict[str, float] = {}
    for k, v in prior.items():
        c = normalize_sector_name(k)
        if c is not None:
            prior_norm[c] = prior_norm.get(c, 0.0) + _num(v)

    # Aggregate current (in case caller passed duplicate/variant sector keys).
    current_norm: Dict[str, float] = {}
    for k, v in (mv_current or {}).items():
        c = normalize_sector_name(k)
        if c is not None:
            current_norm[c] = current_norm.get(c, 0.0) + _num(v)

    for sector, cur in current_norm.items():
        prv = prior_norm.get(sector)
        if prv is None:
            net_flow: Optional[float] = None
            pct_change: Optional[float] = None
            direction = "flat"
        else:
            net_flow = float(round(cur - prv, 2))
            pct_change = (net_flow / prv) if prv > 0 else None
            if pct_change is None:
                direction = "flat"
            elif pct_change >= min_pct_flag:
                direction = "inflow"
            elif pct_change <= -min_pct_flag:
                direction = "outflow"
            else:
                direction = "flat"

        out[sector] = {
            "sector": sector,
            "etf": SECTOR_TO_ETF.get(sector),
            "mv_current": float(round(cur, 2)),
            "mv_prior": (float(round(prv, 2)) if prv is not None else None),
            "net_flow": net_flow,
            "pct_change": (float(round(pct_change, 4)) if pct_change is not None else None),
            "direction": direction,
            "source": "13f_institutional",
            "lagging": True,
        }

    return out


# --------------------------------------------------------------------------- #
# PURE fusion — combine the (timely) insider score with optional (lagging) 13F
# --------------------------------------------------------------------------- #
def fuse_smart_money(
    insider_by_sector: Mapping[str, Mapping[str, Any]],
    f13f_by_sector: Optional[Mapping[str, Mapping[str, Any]]] = None,
    *,
    f13f_inflow_bonus: float = 8.0,
    f13f_outflow_penalty: float = 8.0,
) -> Dict[str, Dict[str, Any]]:
    """Fuse the timely insider score with the optional, lagging 13F flow.

    The **insider cluster score dominates** (it is the timely, reliable signal).
    13F — when supplied — only nudges the score: a confirming institutional
    *inflow* adds a small bonus, an *outflow* subtracts a small penalty. 13F can
    surface a sector on its own only at a deliberately muted score, and that row
    is marked ``lagging=True``. This keeps stale quarterly data from masquerading
    as fresh conviction.

    PURE / deterministic. Returns a fresh dict; inputs are not mutated.

    Parameters
    ----------
    insider_by_sector : mapping
        Output of :func:`aggregate_clusters_by_sector`.
    f13f_by_sector : mapping, optional
        Output of :func:`aggregate_13f_by_sector`. If ``None``/empty, the
        insider scores pass through unchanged.
    f13f_inflow_bonus : float, default 8.0
        Points added when 13F shows confirming institutional inflow.
    f13f_outflow_penalty : float, default 8.0
        Points subtracted when 13F shows institutional outflow.

    Returns
    -------
    dict
        ``{canonical_sector: fused_dict}`` sorted by descending ``score``.
        Each value carries ``score`` (0..100 clamped), ``insider_score``,
        ``insider`` (the source row or ``None``), ``f13f`` (the source row or
        ``None``), and ``lagging`` (``True`` only when the sector rests purely on
        13F data).
    """
    f13f = dict(f13f_by_sector or {})
    fused: Dict[str, Dict[str, Any]] = {}

    sectors = set(insider_by_sector or {}) | set(f13f)
    for sector in sectors:
        ins = insider_by_sector.get(sector) if insider_by_sector else None
        inst = f13f.get(sector)

        insider_score = _num(ins.get("score")) if ins else 0.0
        score = insider_score
        lagging = False

        if inst is not None:
            direction = inst.get("direction")
            if direction == "inflow":
                score += f13f_inflow_bonus
            elif direction == "outflow":
                score -= f13f_outflow_penalty
            if ins is None:
                # Sector rests purely on lagging 13F: muted, flagged.
                lagging = True

        fused[sector] = {
            "sector": sector,
            "etf": SECTOR_TO_ETF.get(sector),
            "score": float(max(0.0, min(100.0, round(score, 2)))),
            "insider_score": float(round(insider_score, 2)),
            "insider": dict(ins) if ins else None,
            "f13f": dict(inst) if inst else None,
            "lagging": lagging,
        }

    return dict(
        sorted(fused.items(), key=lambda kv: kv[1]["score"], reverse=True)
    )


# --------------------------------------------------------------------------- #
# IO function — reuse fetch_form4 + cluster_buys, tag clusters with sector.
# Clearly marked, exception-wrapped, degrades to []. Never raises.
# --------------------------------------------------------------------------- #
def fetch_sector_insider_clusters(
    tickers: Iterable[str],
    *,
    lookback_days: int = 14,
    window_days: int = 7,
    min_insiders: int = 2,
) -> List[Dict[str, Any]]:
    """Fetch Form-4 buys for a universe of tickers and return SECTOR-tagged clusters.

    IO. For each ticker this reuses ``analytics.insider.fetch_form4`` (the only
    SEC-touching code, already UA/rate-limit-compliant and self-throttling),
    accumulates the filings, runs ``analytics.insider.cluster_buys`` once over
    the combined set (clustering is per-issuer, so cross-ticker pooling is safe),
    and tags each resulting cluster with its issuer's GICS sector via
    ``sectors.sector_for_ticker`` (process-cached). The tagged clusters are the
    exact input ::func:`aggregate_clusters_by_sector` consumes.

    Robustness contract: **never raises**. A failing ticker fetch, a missing
    dependency, or an unresolvable sector all degrade gracefully — bad tickers
    contribute nothing, sectorless clusters are tagged ``sector=None`` and later
    dropped by the pure aggregator. Returns ``[]`` on total failure.

    Parameters
    ----------
    tickers : iterable of str
        Issuer tickers to scan (e.g. sector-ETF constituents or a watchlist).
    lookback_days : int, default 14
        Passed through to ``fetch_form4`` (filing-date search window).
    window_days, min_insiders : int
        Passed through to ``cluster_buys`` (cluster definition).

    Returns
    -------
    list of dict
        Cluster dicts (``analytics.insider.cluster_buys`` shape) each with an
        added ``sector`` key (canonical GICS name or ``None``).
    """
    try:
        syms: List[str] = []
        seen = set()
        for t in tickers or []:
            s = str(t or "").strip().upper()
            if s and s not in seen:
                seen.add(s)
                syms.append(s)
        if not syms:
            return []

        all_filings: List[Dict[str, Any]] = []
        for sym in syms:
            try:
                all_filings.extend(fetch_form4(sym, lookback_days=lookback_days))
            except Exception as e:  # noqa: BLE001 - one bad ticker must not abort
                logger.info(
                    "smart_money.fetch_sector_insider_clusters: %s fetch failed: %s",
                    sym, e,
                )
                continue

        if not all_filings:
            return []

        clusters = cluster_buys(
            all_filings, window_days=window_days, min_insiders=min_insiders
        )

        for cluster in clusters:
            sym = str(cluster.get("symbol") or "").strip().upper()
            try:
                cluster["sector"] = sector_for_ticker(sym) if sym else None
            except Exception as e:  # noqa: BLE001 - tolerant by contract
                logger.info(
                    "smart_money.fetch_sector_insider_clusters: sector lookup "
                    "failed for %s: %s", sym, e,
                )
                cluster["sector"] = None

        return clusters
    except Exception as e:  # noqa: BLE001 - absolute top-level guard
        logger.warning(
            "smart_money.fetch_sector_insider_clusters failed: %s", e
        )
        return []
