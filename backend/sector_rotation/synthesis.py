"""Synthesis — fuse the 5 rotation streams into one per-sector rotation read.

This is the **capstone** of ``backend/sector_rotation/``. The five stream modules
each answer one question about a sector ("is price leading?", "are insiders
buying?", "is the narrative hot?", "are catalysts firing?", "is policy money
flowing?"). This module fuses them into a single, signed **rotation score** per
sector — positive = capital rotating **IN**, negative = rotating **OUT** — with a
confidence read calibrated to the 80/60 alert bands, then maps that sector-level
view down onto the actual holdings the user owns.

Layering (mirrors the rest of the package)
------------------------------------------
- :func:`fuse_rotation` and :func:`map_to_companies` are **PURE**: numpy/stdlib
  only, all data passed in, deterministic, unit-tested, no network/disk/clock.
- :func:`run_sector_rotation` is the **only** IO function. It calls each stream's
  exception-wrapped fetcher, tolerates partial results (any stream can be empty),
  runs the pure fusion, and returns the full sweep plus a digest-ready summary.
  It never raises into the caller.

Fusion design (why these weights)
---------------------------------
The research spec's simplified ranking is
``RS_Ratio*0.4 + RS_Momentum*0.3 + ROC*0.2 + News*0.1`` — i.e. **price/RRG is the
backbone (~0.9 of the simple model)** and narrative only tilts. We keep that
spirit but (a) normalize every stream to a common signed ``[-100, +100]`` scale
so they are blendable, and (b) widen the tilt set to the four non-price streams:

    market (RRG/price)  0.50   <- backbone, dominates
    smart_money         0.18   <- timely, high-conviction (insider Code-P buys)
    catalyst            0.12   <- earnings/econ pressure (signed)
    media               0.12   <- narrative sentiment + volume
    government          0.08   <- lagging policy/STOCK-Act money (de-weighted)

Weights are **renormalized over the streams actually present** for a sector, so a
sector seen only by price still gets a sensible (price-only) score, and a missing
stream never silently pulls the score toward zero. Market is *strongly* preferred
but not mandatory: if price is missing but other streams fired, we still score.

Phase = the RRG quadrant from the market stream (Leading / Improving / Weakening /
Lagging / Neutral), the canonical rotation-cycle label.

Confidence (0..100, for the 80/60 bands)
----------------------------------------
Confidence rises with (1) the **magnitude** of the fused score (strong reads are
more actionable), (2) **stream coverage** (more independent confirmations), and
(3) **agreement** (streams pointing the same way). It is deliberately damped when
the only data is lagging (13F / congressional) so stale money cannot manufacture
an 80-confidence alert. ``>=80`` -> immediate alert; ``60..80`` -> watchlist;
``<60`` -> log only — the Tradeskeebot thresholds.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sector_rotation.sectors import (
    SECTOR_ETFS,
    SECTOR_ETF_SYMBOLS,
    SECTOR_TO_ETF,
    etf_to_sector,
    normalize_sector_name,
    sector_for_ticker,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #
#: Base blend weights. Renormalized per-sector over whichever streams are present.
STREAM_WEIGHTS: Dict[str, float] = {
    "market": 0.50,
    "smart_money": 0.18,
    "catalyst": 0.12,
    "media": 0.12,
    "government": 0.08,
}

#: Alert bands (Tradeskeebot thresholds) on *confidence*.
CONF_ALERT = 80.0      # >=80 -> immediate alert (rotating-IN/OUT conviction)
CONF_WATCH = 60.0      # 60..80 -> watchlist / monitor

#: Rotation-score bands that name a sector IN / OUT vs. churning.
SCORE_IN = 20.0        # score >= +20 -> rotating IN
SCORE_OUT = -20.0      # score <= -20 -> rotating OUT

#: Per-quadrant baseline contribution from the RRG phase alone (signed, /100 of
#: the market sub-score's "structural" half — see :func:`_market_subscore`).
_QUADRANT_BASE: Dict[str, float] = {
    "Leading": 60.0,     # in the bullish corner: rotate IN
    "Improving": 25.0,   # early rotation IN
    "Weakening": -25.0,  # losing steam
    "Lagging": -60.0,    # bearish corner: rotate OUT
    "Neutral": 0.0,
}

_ALL_STREAMS = ("market", "smart_money", "media", "catalyst", "government")


# --------------------------------------------------------------------------- #
# small pure helpers
# --------------------------------------------------------------------------- #
def _num(x: Any) -> Optional[float]:
    """Best-effort float, or ``None`` for missing/non-finite values."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return v


def _clamp(x: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, x)))


def _sector_name(key: str) -> str:
    """Resolve a stream key (ETF symbol or sector name) to a canonical sector name."""
    return etf_to_sector(key) or normalize_sector_name(key) or key


# --------------------------------------------------------------------------- #
# Per-stream normalization to a signed [-100, +100] sub-score.
# Each returns (subscore, present_bool, lagging_bool). ``present=False`` means the
# stream had nothing for this sector and must be excluded from the blend.
# --------------------------------------------------------------------------- #
def _market_subscore(block: Optional[Mapping[str, Any]]) -> tuple[float, bool, str]:
    """Price/RRG -> signed [-100,100] + phase.

    Combines (a) the RRG **quadrant baseline** (structural position in the
    rotation cycle) with (b) a **momentum tilt** from RS-Ratio / RS-Momentum
    distance above/below 100 and the multi-timeframe ROC. Returns
    ``(subscore, present, phase)``. ``present`` is False only when there is no
    usable RRG read at all (quadrant Neutral *and* no ratio/momentum/ROC).
    """
    if not block:
        return 0.0, False, "Neutral"

    quadrant = str(block.get("quadrant") or "Neutral")
    base = _QUADRANT_BASE.get(quadrant, 0.0)

    ratio = _num(block.get("rs_ratio"))
    mom = _num(block.get("rs_momentum"))
    # RS-Ratio/Momentum are ~100-centered z-scores; (x-100) is the signed tilt.
    rs_tilt = 0.0
    rs_seen = False
    if ratio is not None:
        rs_tilt += _clamp((ratio - 100.0) * 6.0, -40.0, 40.0)
        rs_seen = True
    if mom is not None:
        rs_tilt += _clamp((mom - 100.0) * 6.0, -40.0, 40.0)
        rs_seen = True

    # Multi-timeframe ROC: average of available windows, scaled (a +10% 1m move
    # is a strong tilt). Cap so a single blow-off bar cannot dominate.
    roc = block.get("roc") or {}
    roc_vals = [v for v in (_num(roc.get(k)) for k in ("1w", "1m", "3m")) if v is not None]
    roc_tilt = 0.0
    roc_seen = False
    if roc_vals:
        roc_tilt = _clamp((sum(roc_vals) / len(roc_vals)) * 2.0, -30.0, 30.0)
        roc_seen = True

    present = quadrant != "Neutral" or rs_seen or roc_seen
    # Structural half (quadrant) + momentum half (rs + roc), kept in range.
    sub = _clamp(base * 0.6 + rs_tilt * 0.6 + roc_tilt)
    return sub, present, quadrant


def _smart_money_subscore(row: Optional[Mapping[str, Any]]) -> tuple[float, bool, bool]:
    """Insider Code-P / 13F -> signed [-100,100].

    The smart-money stream's ``score`` is a 0..100 *conviction* of buying (it does
    not score selling), so it maps to a one-sided positive tilt. A row resting
    purely on lagging 13F is flagged so confidence can de-weight it.
    """
    if not row:
        return 0.0, False, False
    score = _num(row.get("score"))
    if score is None or score <= 0:
        return 0.0, False, bool(row.get("lagging"))
    lagging = bool(row.get("lagging"))
    # 0..100 conviction -> 0..+100 tilt (buying is a rotate-IN pressure).
    return _clamp(score), True, lagging


def _media_subscore(row: Optional[Mapping[str, Any]]) -> tuple[float, bool, bool]:
    """Narrative -> signed [-100,100]. ``narrative_signal`` is ~[-50,+50].

    A sector with **zero news volume** is treated as *not present* (no narrative
    to read), so an empty Finnhub day does not masquerade as a live, neutral
    media confirmation that inflates coverage/confidence.
    """
    if not row:
        return 0.0, False, False
    if _num(row.get("news_volume")) == 0.0 and "news_volume" in row:
        return 0.0, False, False
    sig = _num(row.get("narrative_signal"))
    if sig is None:
        # Fall back to raw sentiment_score in [-1,1] if signal absent.
        sent = _num(row.get("sentiment_score"))
        if sent is None:
            return 0.0, False, False
        return _clamp(sent * 100.0), True, False
    return _clamp(sig * 2.0), True, False  # [-50,50] -> [-100,100]


def _catalyst_subscore(row: Optional[Mapping[str, Any]]) -> tuple[float, bool, bool]:
    """Catalyst -> signed [-100,100]. ``catalyst_score`` is ~[-50,+50]."""
    if not row:
        return 0.0, False, False
    cs = _num(row.get("catalyst_score"))
    if cs is None:
        return 0.0, False, False
    return _clamp(cs * 2.0), True, False  # [-50,50] -> [-100,100]


def _government_subscore(row: Optional[Mapping[str, Any]]) -> tuple[float, bool, bool]:
    """Government/policy -> signed [-100,100]. Always treated as LAGGING.

    Fuses congressional buy/sell skew (the ``flag`` + ``buy_ratio``) with the
    presence of federal contract awards (a one-sided positive tailwind). Both
    sources lag, so this is de-weighted in confidence regardless of magnitude.
    """
    if not row:
        return 0.0, False, True

    sub = 0.0
    present = False

    congress = row.get("congress") or {}
    flag = congress.get("flag")
    buy_ratio = _num(congress.get("buy_ratio"))
    if flag in ("accumulate", "distribute") or buy_ratio is not None:
        present = True
        if buy_ratio is not None:
            # buy_ratio in [0,1]; center at 0.5 -> [-50,+50] tilt.
            sub += _clamp((buy_ratio - 0.5) * 100.0, -50.0, 50.0)
        elif flag == "accumulate":
            sub += 30.0
        elif flag == "distribute":
            sub -= 30.0

    awards = row.get("awards") or {}
    award_value = _num(awards.get("total_value"))
    if award_value is not None and award_value > 0:
        present = True
        # Federal money is a (mild, lagging) positive tailwind; not directional
        # in scale, so add a flat bump for any meaningful award presence.
        sub += 20.0

    return _clamp(sub), present, True


# --------------------------------------------------------------------------- #
# PURE: fuse the five streams into one per-sector rotation read.
# --------------------------------------------------------------------------- #
def _confidence(
    fused_score: float,
    present_weight: float,
    n_present: int,
    n_agree: int,
    only_lagging: bool,
) -> float:
    """Confidence 0..100 calibrated to the 80/60 bands. PURE.

    Blends three ideas:
    - **magnitude** — ``|fused_score|`` (a strong read is more actionable);
    - **coverage** — how much of the total possible stream weight is present
      (more independent confirmations -> more confidence);
    - **agreement** — fraction of present *directional* streams sharing the sign
      of the fused score.

    Damped to a hard ceiling when the only evidence is lagging (13F / congress),
    so stale data can never reach the 80 immediate-alert band on its own.
    """
    magnitude = min(abs(fused_score), 100.0) / 100.0          # 0..1
    coverage = min(present_weight / sum(STREAM_WEIGHTS.values()), 1.0)  # 0..1
    agreement = (n_agree / n_present) if n_present else 0.0    # 0..1

    conf = 100.0 * (0.45 * magnitude + 0.30 * coverage + 0.25 * agreement)
    if only_lagging:
        conf = min(conf, 55.0)  # below the 60 watch band — never an alert alone
    return float(round(_clamp(conf, 0.0, 100.0), 2))


def fuse_rotation(
    streams_by_sector: Mapping[str, Mapping[str, Any]],
    *,
    weights: Mapping[str, float] = STREAM_WEIGHTS,
) -> Dict[str, Dict[str, Any]]:
    """PURE: fuse the 5 streams into a per-sector rotation read.

    Parameters
    ----------
    streams_by_sector : mapping
        ``{canonical_sector: {market{...}, smart_money{...}, media{...},
        catalyst{...}, government{...}}}`` — any stream may be absent / ``None``
        for a given sector. The market block is the per-sector dict from
        :func:`market.build_rotation_block`'s ``sectors`` (keyed by sector here,
        not ETF — :func:`run_sector_rotation` does the re-keying); smart_money /
        media / catalyst / government blocks are the per-sector rows from their
        respective stream aggregators.
    weights : mapping, optional
        Base stream weights; renormalized per-sector over present streams.

    Returns
    -------
    dict
        ``{canonical_sector: {
            "rotation_score": float,   # -100..+100, IN positive / OUT negative
            "confidence":     float,   # 0..100 (80/60 bands)
            "status":         str,     # rotating-IN | rotating-OUT | neutral
            "alert":          str,     # immediate | watch | log
            "phase":          str,     # RRG quadrant (Leading/...)
            "etf":            str|None,
            "components":     {market, smart_money, media, catalyst, government},
            "present":        [stream names that contributed],
            "lagging_only":   bool,
        }}`` sorted by descending ``rotation_score``.

    Pure and deterministic. Inputs are not mutated. A sector with no usable data
    in any stream still yields a neutral row (score 0, confidence 0) rather than
    being dropped, so the full 11-sector frame is preserved when present in input.
    """
    out: Dict[str, Dict[str, Any]] = {}

    for sector_key, streams in (streams_by_sector or {}).items():
        sector = _sector_name(sector_key)
        streams = streams or {}

        m_sub, m_present, phase = _market_subscore(streams.get("market"))
        sm_sub, sm_present, sm_lag = _smart_money_subscore(streams.get("smart_money"))
        md_sub, md_present, _ = _media_subscore(streams.get("media"))
        ca_sub, ca_present, _ = _catalyst_subscore(streams.get("catalyst"))
        gv_sub, gv_present, gv_lag = _government_subscore(streams.get("government"))

        subs = {
            "market": (m_sub, m_present, False),
            "smart_money": (sm_sub, sm_present, sm_lag),
            "media": (md_sub, md_present, False),
            "catalyst": (ca_sub, ca_present, False),
            "government": (gv_sub, gv_present, gv_lag),
        }

        # Renormalize weights over present streams.
        present_names = [name for name, (_, p, _) in subs.items() if p]
        present_weight = sum(float(weights.get(n, 0.0)) for n in present_names)

        components: Dict[str, Optional[float]] = {}
        for name, (sub, present, _) in subs.items():
            components[name] = round(sub, 2) if present else None

        if present_weight > 0:
            fused = sum(
                subs[n][0] * float(weights.get(n, 0.0)) for n in present_names
            ) / present_weight
        else:
            fused = 0.0
        fused = _clamp(fused)

        # Agreement: of the present *non-zero* streams, how many share the sign.
        directional = [
            (subs[n][0], n) for n in present_names if abs(subs[n][0]) > 1e-9
        ]
        if directional and abs(fused) > 1e-9:
            sign = 1.0 if fused > 0 else -1.0
            n_agree = sum(1 for s, _ in directional if (s > 0) == (sign > 0))
            n_dir = len(directional)
        else:
            n_agree = n_dir = 0

        lagging_only = bool(present_names) and all(
            subs[n][2] for n in present_names if abs(subs[n][0]) > 1e-9
        ) and bool(directional)

        confidence = _confidence(
            fused, present_weight, n_dir, n_agree, lagging_only
        )

        if fused >= SCORE_IN:
            status = "rotating-IN"
        elif fused <= SCORE_OUT:
            status = "rotating-OUT"
        else:
            status = "neutral"

        if confidence >= CONF_ALERT:
            alert = "immediate"
        elif confidence >= CONF_WATCH:
            alert = "watch"
        else:
            alert = "log"

        out[sector] = {
            "sector": sector,
            "etf": SECTOR_TO_ETF.get(sector),
            "rotation_score": float(round(fused, 2)),
            "confidence": confidence,
            "status": status,
            "alert": alert,
            "phase": phase,
            "components": components,
            "present": present_names,
            "lagging_only": lagging_only,
        }

    return dict(
        sorted(out.items(), key=lambda kv: kv[1]["rotation_score"], reverse=True)
    )


# --------------------------------------------------------------------------- #
# PURE: map the sector-level rotation read down onto holdings.
# --------------------------------------------------------------------------- #
def _holding_symbol(h: Any) -> Optional[str]:
    """Extract a ticker from a holding (str or dict with symbol/ticker)."""
    if isinstance(h, str):
        sym = h.strip().upper()
        return sym or None
    if isinstance(h, Mapping):
        for k in ("symbol", "ticker", "Symbol", "Ticker"):
            v = h.get(k)
            if v:
                return str(v).strip().upper()
    return None


def map_to_companies(
    rotation_by_sector: Mapping[str, Mapping[str, Any]],
    holdings: Sequence[Any],
    *,
    sector_lookup=sector_for_ticker,
    top_n_candidates: int = 5,
) -> Dict[str, Any]:
    """PURE-by-injection: tag holdings with their sector's rotation status.

    Each holding is resolved to a GICS sector (via ``sector_lookup`` — injected
    so tests stay offline) and tagged with that sector's rotation read: a
    rotating-IN sector is a **tailwind**, rotating-OUT is a **risk flag**. Also
    surfaces the strongest rotating-IN sectors and, from the holdings present,
    candidate tickers sitting in them.

    Parameters
    ----------
    rotation_by_sector : mapping
        Output of :func:`fuse_rotation` (``{sector: {...}}``).
    holdings : sequence
        Tickers (``str``) or holding dicts carrying a ``symbol``/``ticker`` (and
        optionally a ``sector``) key.
    sector_lookup : callable, default :func:`sectors.sector_for_ticker`
        ``ticker -> sector|None``. Injected so unit tests never hit the network.
    top_n_candidates : int, default 5
        How many top rotating-IN sectors to surface (with their candidate tickers
        drawn from the supplied holdings).

    Returns
    -------
    dict
        ``{
            "tagged": [ {symbol, sector, etf, rotation_score, confidence,
                         status, alert, phase, tag} ],   # tag: tailwind|risk|neutral|unknown
            "tailwinds": [symbols in rotating-IN sectors],
            "risks":     [symbols in rotating-OUT sectors],
            "top_in_sectors": [ {sector, etf, rotation_score, confidence,
                                  candidate_tickers:[...] } ],
        }``

    Pure given a pure ``sector_lookup``. Inputs are not mutated.
    """
    rotation = dict(rotation_by_sector or {})
    tagged: List[Dict[str, Any]] = []
    tailwinds: List[str] = []
    risks: List[str] = []
    by_sector_symbols: Dict[str, List[str]] = {}

    seen: set[str] = set()
    for h in holdings or []:
        sym = _holding_symbol(h)
        if not sym or sym in seen:
            continue
        seen.add(sym)

        # Prefer a sector carried on the holding dict; else look it up.
        sector = None
        if isinstance(h, Mapping):
            sector = normalize_sector_name(h.get("sector")) if h.get("sector") else None
        if sector is None:
            try:
                sector = sector_lookup(sym)
            except Exception as e:  # noqa: BLE001 - lookup must never sink the map
                logger.debug("map_to_companies: sector lookup failed for %s: %s", sym, e)
                sector = None

        rot = rotation.get(sector) if sector else None
        if rot is None:
            tagged.append({
                "symbol": sym,
                "sector": sector,
                "etf": SECTOR_TO_ETF.get(sector) if sector else None,
                "rotation_score": None,
                "confidence": None,
                "status": None,
                "alert": None,
                "phase": None,
                "tag": "unknown" if sector is None else "neutral",
            })
            continue

        status = rot.get("status")
        if status == "rotating-IN":
            tag = "tailwind"
            tailwinds.append(sym)
        elif status == "rotating-OUT":
            tag = "risk"
            risks.append(sym)
        else:
            tag = "neutral"

        by_sector_symbols.setdefault(sector, []).append(sym)
        tagged.append({
            "symbol": sym,
            "sector": sector,
            "etf": rot.get("etf"),
            "rotation_score": rot.get("rotation_score"),
            "confidence": rot.get("confidence"),
            "status": status,
            "alert": rot.get("alert"),
            "phase": rot.get("phase"),
            "tag": tag,
        })

    # Top rotating-IN sectors (sorted by score), with candidate tickers from holdings.
    in_sectors = [
        v for v in rotation.values() if v.get("status") == "rotating-IN"
    ]
    in_sectors.sort(key=lambda v: v.get("rotation_score", 0.0), reverse=True)
    top_in = []
    for v in in_sectors[: max(0, int(top_n_candidates))]:
        sec = v.get("sector")
        top_in.append({
            "sector": sec,
            "etf": v.get("etf"),
            "rotation_score": v.get("rotation_score"),
            "confidence": v.get("confidence"),
            "phase": v.get("phase"),
            "candidate_tickers": sorted(by_sector_symbols.get(sec, [])),
        })

    return {
        "tagged": tagged,
        "tailwinds": sorted(set(tailwinds)),
        "risks": sorted(set(risks)),
        "top_in_sectors": top_in,
    }


# =========================================================================== #
# IO ORCHESTRATOR — the ONLY network-touching code in this module.
# Calls each stream's exception-wrapped fetcher, tolerates partial results,
# runs the PURE fusion, and degrades gracefully. Never raises into the caller.
# =========================================================================== #
def _safe(label: str, fn, *args, default=None, **kwargs):
    """Run an IO fetcher, swallowing any failure and returning ``default``."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - orchestrator must never raise
        logger.warning("run_sector_rotation: %s failed: %s", label, e)
        return default


def _collect_streams_by_sector(
    market_block: Mapping[str, Any],
    smart_money: Mapping[str, Mapping[str, Any]],
    media: Mapping[str, Mapping[str, Any]],
    catalyst: Mapping[str, Mapping[str, Any]],
    congress: Mapping[str, Any],
    awards: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Re-key all stream outputs onto canonical sector names for fusion. PURE.

    The market block is keyed by ETF symbol; media may be keyed by ETF; the
    others are keyed by sector name. Congress/awards are ``{"sectors": {...}}``
    wrappers. This normalizes everything to ``{sector: {stream: row}}`` so
    :func:`fuse_rotation` sees one consistent frame covering all 11 sectors.
    """
    frame: Dict[str, Dict[str, Any]] = {
        sector: {} for sector in SECTOR_ETFS.values()
    }

    def _slot(sector: Optional[str]) -> Optional[Dict[str, Any]]:
        if not sector:
            return None
        return frame.setdefault(sector, {})

    # market: {etf: row}
    for etf, row in (market_block.get("sectors") or {}).items():
        slot = _slot(etf_to_sector(etf) or (row or {}).get("sector"))
        if slot is not None:
            slot["market"] = row

    # smart_money: {sector: row}
    for key, row in (smart_money or {}).items():
        slot = _slot(_sector_name(key))
        if slot is not None:
            slot["smart_money"] = row

    # media: {etf-or-sector: row}
    for key, row in (media or {}).items():
        slot = _slot(_sector_name(key))
        if slot is not None:
            slot["media"] = row

    # catalyst: {sector: row}
    for key, row in (catalyst or {}).items():
        slot = _slot(_sector_name(key))
        if slot is not None:
            slot["catalyst"] = row

    # government: congress + awards both {"sectors": {sector: row}}
    congress_sectors = (congress or {}).get("sectors") or {}
    awards_sectors = (awards or {}).get("sectors") or {}
    gov_sectors = set(congress_sectors) | set(awards_sectors)
    for key in gov_sectors:
        if key == "Unknown":
            continue
        slot = _slot(_sector_name(key))
        if slot is None:
            continue
        gov_row: Dict[str, Any] = {}
        if key in congress_sectors:
            gov_row["congress"] = congress_sectors[key]
        if key in awards_sectors:
            gov_row["awards"] = awards_sectors[key]
        if gov_row:
            slot["government"] = gov_row

    return frame


def _digest(
    rotation: Mapping[str, Mapping[str, Any]],
    company_map: Mapping[str, Any],
    sources_ok: Mapping[str, bool],
) -> Dict[str, Any]:
    """Build a compact, digest-ready summary (for Telegram / dashboard). PURE."""
    rows = list(rotation.values())
    leaders_in = [r for r in rows if r.get("status") == "rotating-IN"]
    leaders_out = [r for r in rows if r.get("status") == "rotating-OUT"]
    alerts = [r for r in rows if r.get("alert") == "immediate"]

    def _brief(r: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "sector": r.get("sector"),
            "etf": r.get("etf"),
            "rotation_score": r.get("rotation_score"),
            "confidence": r.get("confidence"),
            "phase": r.get("phase"),
            "alert": r.get("alert"),
        }

    return {
        "rotating_in": [_brief(r) for r in leaders_in],
        "rotating_out": [_brief(r) for r in leaders_out],
        "alerts": [_brief(r) for r in alerts],
        "top_in_sectors": company_map.get("top_in_sectors", []),
        "holding_tailwinds": company_map.get("tailwinds", []),
        "holding_risks": company_map.get("risks", []),
        "sources_ok": dict(sources_ok),
        "n_sectors_scored": len(rows),
    }


def run_sector_rotation(
    holdings: Optional[Sequence[Any]] = None,
    *,
    watchlist: Optional[Sequence[str]] = None,
    news_lookback_days: int = 1,
    earnings_days_ahead: int = 5,
    congress_lookback_days: int = 90,
    awards_lookback_days: int = 7,
) -> Dict[str, Any]:
    """IO: run the full 5-stream rotation sweep and fuse it. Never raises.

    Calls each stream's exception-wrapped fetcher (any of which may degrade to an
    empty result with no network/key), runs the PURE :func:`fuse_rotation`, maps
    the result onto ``holdings`` via :func:`map_to_companies`, and returns the
    full sweep plus a digest-ready summary. A failure or no-data condition in any
    one stream simply drops that stream from the blend — the sweep still returns.

    The smart-money / congress universe is the supplied ``holdings`` +
    ``watchlist`` (we only have per-ticker SEC/Finnhub endpoints, so we scan the
    tickers we care about); the price/media/catalyst streams cover all 11 sector
    ETFs directly.

    Parameters
    ----------
    holdings : sequence, optional
        Portfolio holdings (tickers or dicts) to tag with rotation status.
    watchlist : sequence of str, optional
        Extra tickers to include in the per-ticker smart-money / congress scans.
    *_days / *_ahead : int
        Lookback windows forwarded to the respective fetchers.

    Returns
    -------
    dict
        ``{
            "rotation":   {sector: fused row},      # full fuse_rotation output
            "companies":  {...},                    # map_to_companies output
            "market":     {...},                    # raw market rotation block
            "summary":    {...},                    # digest-ready
            "sources_ok": {market, smart_money, media, catalyst, government: bool},
        }``
    """
    holdings = list(holdings or [])
    watchlist = list(watchlist or [])

    # Per-ticker universe for SEC/Finnhub per-symbol endpoints (insider, congress).
    ticker_universe: List[str] = []
    seen: set[str] = set()
    for h in (*holdings, *watchlist):
        sym = _holding_symbol(h)
        if sym and sym not in seen:
            seen.add(sym)
            ticker_universe.append(sym)

    # --- Local imports keep the pure surface import-light & deps optional. ---
    from sector_rotation import market as market_mod
    from sector_rotation import smart_money as sm_mod
    from sector_rotation import media as media_mod
    from sector_rotation import catalyst as cat_mod
    from sector_rotation import government as gov_mod

    sources_ok: Dict[str, bool] = {k: False for k in _ALL_STREAMS}

    # 1) Market / price (backbone) — covers all 11 ETFs directly.
    market_block = _safe(
        "market", market_mod.scan_market_rotation, default={}
    ) or {}
    sources_ok["market"] = bool((market_block or {}).get("sectors"))

    # 2) Smart money — SEC Form-4 clusters over the ticker universe, by sector.
    smart_money: Dict[str, Any] = {}
    if ticker_universe:
        clusters = _safe(
            "smart_money.fetch", sm_mod.fetch_sector_insider_clusters,
            ticker_universe, default=[],
        ) or []
        insider_by_sector = _safe(
            "smart_money.aggregate", sm_mod.aggregate_clusters_by_sector,
            clusters, default={},
        ) or {}
        smart_money = _safe(
            "smart_money.fuse", sm_mod.fuse_smart_money,
            insider_by_sector, default={},
        ) or {}
    sources_ok["smart_money"] = bool(smart_money)

    # 3) Media / narrative — Finnhub news per sector ETF.
    news = _safe(
        "media.fetch", media_mod.fetch_all_sector_news,
        SECTOR_ETF_SYMBOLS, default={},
        lookback_days=news_lookback_days,
    ) or {}
    media = _safe(
        "media.score", media_mod.score_sectors, news, default={},
    ) or {}
    # "ok" only when at least one sector saw real headline volume — an empty
    # Finnhub day yields all-zero rows that carry no narrative signal.
    sources_ok["media"] = any(
        (_num((r or {}).get("news_volume")) or 0.0) > 0 for r in media.values()
    )

    # 4) Catalyst — earnings calendar clustering + FRED econ releases.
    earnings = _safe(
        "catalyst.earnings", cat_mod.fetch_earnings_calendar, default=[],
        days_ahead=earnings_days_ahead,
    ) or []
    # aggregate_earnings_by_sector is PURE and needs a {ticker: sector} map; the
    # caller resolves tickers out of band (cached, exception-wrapped lookup).
    earnings_t2s: Dict[str, Optional[str]] = {}
    for ev in earnings:
        sym = str((ev or {}).get("symbol") or "").strip().upper()
        if sym and sym not in earnings_t2s:
            earnings_t2s[sym] = _safe(
                "catalyst.sector_lookup", sector_for_ticker, sym, default=None
            )
    earnings_scores = _safe(
        "catalyst.cluster", cat_mod.aggregate_earnings_by_sector, earnings,
        earnings_t2s, default={},
    ) or {}
    earnings_scored = _safe(
        "catalyst.score_cluster", cat_mod.score_earnings_clustering,
        earnings_scores, default={},
    ) or {}
    econ = _safe(
        "catalyst.econ", cat_mod.fetch_econ_releases, default=[],
    ) or []
    catalyst = _safe(
        "catalyst.pressure", cat_mod.score_catalyst_pressure,
        earnings_scored, econ, default={},
    ) or {}
    sources_ok["catalyst"] = bool(catalyst)

    # 5) Government / policy — congressional trades + federal awards.
    congress_trades: List[Dict[str, Any]] = []
    for sym in ticker_universe:
        rows = _safe(
            "government.congress", gov_mod.fetch_congressional_trades, sym,
            default=[], lookback_days=congress_lookback_days,
        ) or []
        congress_trades.extend(rows)
    congress = _safe(
        "government.congress_agg", gov_mod.aggregate_congress_by_sector,
        congress_trades, default={"sectors": {}},
    ) or {"sectors": {}}
    awards_rows = _safe(
        "government.awards", gov_mod.fetch_contract_awards, default=[],
        lookback_days=awards_lookback_days,
    ) or []
    awards = _safe(
        "government.awards_agg", gov_mod.aggregate_awards_by_sector, awards_rows,
        default={"sectors": {}},
    ) or {"sectors": {}}
    sources_ok["government"] = bool(
        (congress.get("sectors") or {}) or (awards.get("sectors") or {})
    )

    # --- Fuse (PURE) ---
    frame = _collect_streams_by_sector(
        market_block, smart_money, media, catalyst, congress, awards
    )
    rotation = fuse_rotation(frame)
    companies = map_to_companies(rotation, holdings)
    summary = _digest(rotation, companies, sources_ok)

    return {
        "rotation": rotation,
        "companies": companies,
        "market": market_block,
        "summary": summary,
        "sources_ok": sources_ok,
    }


__all__ = [
    "STREAM_WEIGHTS",
    "CONF_ALERT",
    "CONF_WATCH",
    "SCORE_IN",
    "SCORE_OUT",
    "fuse_rotation",
    "map_to_companies",
    "run_sector_rotation",
]
