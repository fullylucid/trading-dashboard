"""The GOVERNMENT angle of sector rotation — STOCK Act trades + federal awards.

Two free, public "smart money / policy" data streams, each aggregated **by
GICS sector** so they can feed the rotation fusion layer alongside price/RRG,
insider Form-4s, etc.:

1. **Congressional trading (STOCK Act)** — US House/Senate members must disclose
   their securities transactions. We aggregate disclosed buys vs. sells **per
   sector** and compute a per-sector buy ratio / net flow.

   ⚠️  **~45-day disclosure lag.** The STOCK Act gives members up to ~45 days
   after a trade to file. So a "congress is buying Energy" reading reflects
   trades that happened *up to a month and a half ago* — the move it implies may
   already be priced in. Every congressional aggregate produced here carries an
   explicit ``disclosure_lag_days`` annotation (default 45) and a
   ``stale_after`` date so the fusion/UI layer can de-weight it. Treat it as
   **confirmation, never a trigger.**

2. **Federal contract awards (USAspending.gov)** — federal prime-award
   obligations. We map each award's recipient ticker -> GICS sector and sum
   award value / count **per sector** (e.g. a defense-spending spike lighting up
   Industrials). USAspending is free and unauthenticated.

Layering (mirrors ``backend/analytics/`` and the rest of this package):

- **PURE helpers** (numpy/stdlib only, no network, no disk, deterministic,
  unit-tested directly with crafted record dicts): :func:`naics_to_sector`,
  :func:`normalize_congress_trade`, :func:`aggregate_congress_by_sector`,
  :func:`normalize_award`, :func:`aggregate_awards_by_sector`. They take
  already-fetched record dicts IN and return per-sector aggregates.
- **IO functions** (the ONLY network-touching code; clearly marked,
  exception-wrapped, compliant ``User-Agent`` + conservative throttle, degrade
  to ``[]`` and **never raise**): :func:`fetch_congressional_trades`,
  :func:`fetch_contract_awards`.

Record-dict schemas (the contract between IO and PURE layers)
-------------------------------------------------------------
Congressional trade (raw / pre-normalized, tolerant of vendor key variants)::

    {
        "symbol":          "LMT",
        "transactionType": "Purchase",   # or "buy"/"sell"/"Sale (Full)"/...
        "transactionDate": "2026-04-01",  # trade date (NOT filing date)
        "filingDate":      "2026-05-10",  # disclosure date (~45d later)
        "name":            "Jane Doe",    # member name
        "amountFrom":      15001,         # disclosed $ range low (optional)
        "amountTo":        50000,         # disclosed $ range high (optional)
    }

Federal award (raw, USAspending ``spending_by_award`` row, tolerant)::

    {
        "Recipient Name":  "LOCKHEED MARTIN CORP",
        "recipient_ticker": "LMT",       # if a caller resolved it
        "Award Amount":    1.2e9,
        "naics_code":      "336411",
        "Awarding Agency": "Department of Defense",
        "Award ID":        "...",
    }

Sources / references
--------------------
- STOCK Act (P.L. 112-105) — disclosure-lag rationale.
- Finnhub ``/stock/congressional-trading`` (free tier, per-symbol, 60 req/min):
  https://finnhub.io/docs/api/congressional-trading
- USAspending.gov API (free, no auth): https://api.usaspending.gov/
  ``POST /api/v2/search/spending_by_award/``
- NAICS (Census) vs GICS (MSCI/S&P) — manual range mapping per research spec.
- Package research spec (data-source / method design).
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .sectors import normalize_sector_name, sector_for_ticker

logger = logging.getLogger(__name__)

__all__ = [
    "CONGRESS_DISCLOSURE_LAG_DAYS",
    "naics_to_sector",
    "normalize_congress_trade",
    "aggregate_congress_by_sector",
    "normalize_award",
    "aggregate_awards_by_sector",
    "fetch_congressional_trades",
    "fetch_contract_awards",
]

#: Statutory upper bound on the STOCK Act trade->disclosure delay, in days.
#: Used to annotate every congressional aggregate so downstream layers know how
#: stale the signal is (and to compute a ``stale_after`` date).
CONGRESS_DISCLOSURE_LAG_DAYS = 45


# --------------------------------------------------------------------------- #
# PURE: NAICS -> GICS sector mapping
# --------------------------------------------------------------------------- #
# NAICS (industry classification used by federal contracting) does not line up
# with GICS (the sector taxonomy our ETF universe uses). We map by the leading
# digits of the NAICS code to a canonical GICS sector name (a key of
# ``sectors.SECTOR_TO_ETF``). Ranges follow the research spec; longer prefixes
# are checked first so a specific code (e.g. 3344 Semiconductors -> Information
# Technology) wins over its broader parent (33 Manufacturing -> Industrials).
#
# This is intentionally coarse and best-effort: NAICS->GICS is many-to-many and
# imperfect. Unknown codes return ``None`` and are bucketed as "Unknown" by the
# aggregator rather than silently misattributed.
_NAICS_PREFIX_TO_SECTOR: Dict[str, str] = {
    # --- 4-digit (most specific) -----------------------------------------
    "3344": "Information Technology",   # Semiconductor & electronic components
    "3345": "Information Technology",   # Navigational/measuring/control instruments
    "4236": "Information Technology",   # Computer & electronics merchant wholesale
    "5112": "Information Technology",   # Software publishers
    "5413": "Industrials",             # Architectural / engineering services
    "5415": "Information Technology",   # Computer systems design services
    "3364": "Industrials",             # Aerospace product & parts manufacturing
    "2111": "Energy",                  # Oil & gas extraction
    "3254": "Health Care",             # Pharmaceutical & medicine manufacturing
    "3391": "Health Care",             # Medical equipment & supplies manufacturing
    # --- 3-digit ---------------------------------------------------------
    "325": "Materials",                # Chemical manufacturing
    "211": "Energy",                   # Oil & gas extraction (parent)
    "212": "Materials",                # Mining (except oil & gas)
    "213": "Energy",                   # Support activities for mining
    "221": "Utilities",                # Utilities (electric/gas/water)
    "236": "Industrials",              # Construction of buildings
    "237": "Industrials",              # Heavy & civil engineering construction
    "311": "Consumer Staples",         # Food manufacturing
    "312": "Consumer Staples",         # Beverage & tobacco manufacturing
    "423": "Industrials",              # Merchant wholesalers, durable goods
    "445": "Consumer Staples",         # Food & beverage retailers
    "511": "Communication Services",   # Publishing (incl. software at 5112 above)
    "517": "Communication Services",   # Telecommunications
    "518": "Information Technology",   # Data processing / hosting
    "522": "Financials",               # Credit intermediation
    "523": "Financials",               # Securities / commodity contracts
    "524": "Financials",               # Insurance carriers
    "531": "Real Estate",              # Real estate
    "541": "Industrials",              # Professional/scientific/technical (default)
    "621": "Health Care",              # Ambulatory health care services
    "622": "Health Care",              # Hospitals
    # --- 2-digit (broadest fallback) -------------------------------------
    "11": "Materials",                 # Agriculture/forestry/fishing
    "21": "Energy",                    # Mining/quarrying/oil & gas
    "22": "Utilities",                 # Utilities
    "23": "Industrials",               # Construction
    "31": "Consumer Staples",          # Manufacturing (food-leaning low 31x)
    "32": "Materials",                 # Manufacturing (chemicals/materials-leaning)
    "33": "Industrials",               # Manufacturing (machinery/transport)
    "42": "Industrials",               # Wholesale trade
    "44": "Consumer Discretionary",    # Retail trade
    "45": "Consumer Discretionary",    # Retail trade
    "48": "Industrials",               # Transportation
    "49": "Industrials",               # Transportation & warehousing
    "51": "Communication Services",    # Information
    "52": "Financials",                # Finance & insurance
    "53": "Real Estate",               # Real estate & rental
    "54": "Industrials",               # Professional/scientific/technical
    "62": "Health Care",               # Health care & social assistance
}


def naics_to_sector(naics_code: Any) -> Optional[str]:
    """PURE: map a NAICS code to a canonical GICS sector name, or ``None``.

    Matches by **longest leading-digit prefix** (4 -> 3 -> 2 digits) so a
    specific industry (e.g. ``3344`` semiconductors -> Information Technology)
    overrides its broad parent (``33`` manufacturing -> Industrials).

    Tolerant of ``int``/``str`` input and of codes with trailing detail digits
    (a 6-digit NAICS like ``"336411"`` matches its ``"3364"`` prefix). Returns a
    key of :data:`sectors.SECTOR_TO_ETF`, or ``None`` if no prefix matches.

    >>> naics_to_sector("336411")
    'Industrials'
    >>> naics_to_sector(334413)
    'Information Technology'
    >>> naics_to_sector("9999") is None
    True
    """
    if naics_code is None:
        return None
    digits = "".join(ch for ch in str(naics_code).strip() if ch.isdigit())
    if not digits:
        return None
    for plen in (4, 3, 2):
        if len(digits) >= plen:
            sector = _NAICS_PREFIX_TO_SECTOR.get(digits[:plen])
            if sector is not None:
                return sector
    return None


# --------------------------------------------------------------------------- #
# PURE: congressional-trade normalization + per-sector aggregation
# --------------------------------------------------------------------------- #
# Vendor strings for the transaction side vary a lot ("Purchase", "buy",
# "Sale (Full)", "Sale (Partial)", "exchange", ...). We classify each into
# "buy" / "sell" / "other" (the last is excluded from the buy/sell ratio).
_BUY_TOKENS = ("purchase", "buy", "bought", "acqui")
_SELL_TOKENS = ("sale", "sell", "sold", "dispos")


def _classify_side(raw: Any) -> str:
    """PURE: classify a transaction-type string into 'buy'/'sell'/'other'."""
    s = str(raw or "").strip().lower()
    if not s:
        return "other"
    # Check sell tokens first: "sale" must not be caught by a stray "a" etc.
    if any(tok in s for tok in _SELL_TOKENS):
        return "sell"
    if any(tok in s for tok in _BUY_TOKENS):
        return "buy"
    return "other"


def _amount_midpoint(trade: Dict[str, Any]) -> float:
    """PURE: best-effort dollar size of a disclosed trade (range midpoint).

    Disclosures report a $ *range*. Prefer an explicit numeric ``amount``; else
    use the midpoint of ``amountFrom``/``amountTo``; else 0.0. Never raises.
    """
    explicit = trade.get("amount")
    lo = trade.get("amountFrom", trade.get("amount_from"))
    hi = trade.get("amountTo", trade.get("amount_to"))

    def _f(v: Any) -> Optional[float]:
        try:
            if v is None or v == "":
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    e = _f(explicit)
    if e is not None and e > 0:
        return e
    flo, fhi = _f(lo), _f(hi)
    if flo is not None and fhi is not None:
        return (flo + fhi) / 2.0
    if fhi is not None:
        return fhi
    if flo is not None:
        return flo
    return 0.0


def _parse_iso_date(value: Any) -> Optional[date]:
    """PURE: tolerant YYYY-MM-DD(THH:MM:SS) parse; ``None`` on failure."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("/", "-")
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_congress_trade(
    trade: Dict[str, Any],
    *,
    sector_lookup=sector_for_ticker,
) -> Optional[Dict[str, Any]]:
    """PURE-ish: normalize one raw congressional-trade dict into a tidy record.

    Resolves the trade's ticker to a GICS sector via ``sector_lookup`` (default
    :func:`sectors.sector_for_ticker`), classifies the side, and extracts the
    dollar midpoint and dates. Returns ``None`` for rows we cannot place
    (no symbol, or a non-buy/non-sell "other" side).

    ``sector_lookup`` is injectable so unit tests stay PURE (pass a dict's
    ``.get`` or a stub) — with the default it performs the package's cached IO
    sector resolution. Pass ``sector_lookup=lambda s: <map>.get(s)`` in tests.

    Returns a dict::

        {"symbol", "sector", "side", "amount", "trade_date", "filing_date",
         "member"}

    or ``None`` if the row is unusable.
    """
    symbol = str(
        trade.get("symbol") or trade.get("ticker") or trade.get("Ticker") or ""
    ).strip().upper()
    if not symbol:
        return None

    side = _classify_side(
        trade.get("transactionType")
        or trade.get("transaction_type")
        or trade.get("type")
        or trade.get("Transaction")
    )
    if side == "other":
        return None

    try:
        sector = sector_lookup(symbol)
    except Exception:  # noqa: BLE001 - lookup must never break aggregation
        sector = None
    sector = normalize_sector_name(sector) or sector  # idempotent if already canonical

    return {
        "symbol": symbol,
        "sector": sector,  # may be None if unresolved
        "side": side,
        "amount": _amount_midpoint(trade),
        "trade_date": (
            d.isoformat()
            if (d := _parse_iso_date(
                trade.get("transactionDate") or trade.get("transaction_date")
            ))
            else None
        ),
        "filing_date": (
            d.isoformat()
            if (d := _parse_iso_date(
                trade.get("filingDate") or trade.get("filing_date")
            ))
            else None
        ),
        "member": str(
            trade.get("name") or trade.get("member") or trade.get("representative") or ""
        ).strip(),
    }


def aggregate_congress_by_sector(
    trades: List[Dict[str, Any]],
    *,
    sector_lookup=sector_for_ticker,
    disclosure_lag_days: int = CONGRESS_DISCLOSURE_LAG_DAYS,
    asof: Optional[date] = None,
) -> Dict[str, Any]:
    """PURE: aggregate disclosed congressional trades into per-sector signals.

    For each canonical GICS sector we count buys vs. sells, sum the disclosed
    dollar midpoints, and compute::

        net_buys   = n_buys - n_sells
        buy_ratio  = n_buys / (n_buys + n_sells)        # None if no buys+sells
        net_dollars = buy_dollars - sell_dollars

    Per the research spec, a sector with ``buy_ratio > 0.65`` is flagged
    ``"accumulate"`` and ``< 0.35`` ``"distribute"`` (else ``"neutral"``).

    The whole result is annotated with the **disclosure lag** so downstream
    layers de-weight it: ``disclosure_lag_days`` and a ``stale_after`` date
    (``asof - disclosure_lag_days``) marking how far back the freshest trade a
    filing could be describing is. ``asof`` defaults to today (UTC).

    Rows whose ticker did not resolve to a sector are tallied under the
    ``"Unknown"`` key so nothing is silently dropped, but ``"Unknown"`` is never
    flagged.

    Parameters
    ----------
    trades : list of dict
        Raw congressional-trade dicts (see module schema). Already-normalized
        dicts (output of :func:`normalize_congress_trade`) are also accepted.
    sector_lookup : callable, default :func:`sectors.sector_for_ticker`
        ``symbol -> sector|None``. Injected for PURE unit testing.
    disclosure_lag_days : int, default 45
        Statutory STOCK Act lag used for the staleness annotation.
    asof : datetime.date, optional
        Reference "today" for the staleness date. Defaults to today (UTC).

    Returns
    -------
    dict
        ``{"sectors": {sector: {...}}, "disclosure_lag_days": int,
        "stale_after": "YYYY-MM-DD", "n_trades": int, "note": str}``.
    """
    if asof is None:
        asof = datetime.now(timezone.utc).date()
    lag = max(0, int(disclosure_lag_days))

    # Accumulators keyed by sector name (or "Unknown").
    agg: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"n_buys": 0, "n_sells": 0, "buy_dollars": 0.0, "sell_dollars": 0.0}
    )

    n_used = 0
    for raw in trades or []:
        # Accept both raw and already-normalized rows.
        if "side" in raw and "sector" in raw and "symbol" in raw:
            rec = raw
        else:
            rec = normalize_congress_trade(raw, sector_lookup=sector_lookup)
        if rec is None:
            continue
        side = rec.get("side")
        if side not in ("buy", "sell"):
            continue
        sector = rec.get("sector") or "Unknown"
        amt = float(rec.get("amount") or 0.0)
        bucket = agg[sector]
        if side == "buy":
            bucket["n_buys"] += 1
            bucket["buy_dollars"] += amt
        else:
            bucket["n_sells"] += 1
            bucket["sell_dollars"] += amt
        n_used += 1

    sectors_out: Dict[str, Any] = {}
    for sector, b in agg.items():
        nb, ns = int(b["n_buys"]), int(b["n_sells"])
        total = nb + ns
        buy_ratio = (nb / total) if total else None
        if sector == "Unknown" or buy_ratio is None:
            flag = "neutral"
        elif buy_ratio > 0.65:
            flag = "accumulate"
        elif buy_ratio < 0.35:
            flag = "distribute"
        else:
            flag = "neutral"
        sectors_out[sector] = {
            "n_buys": nb,
            "n_sells": ns,
            "net_buys": nb - ns,
            "buy_ratio": buy_ratio,
            "buy_dollars": round(b["buy_dollars"], 2),
            "sell_dollars": round(b["sell_dollars"], 2),
            "net_dollars": round(b["buy_dollars"] - b["sell_dollars"], 2),
            "flag": flag,
        }

    return {
        "sectors": sectors_out,
        "disclosure_lag_days": lag,
        "stale_after": (asof - timedelta(days=lag)).isoformat(),
        "n_trades": n_used,
        "note": (
            f"STOCK Act disclosures lag trades by up to {lag} days; trades shown "
            "may be that old. Use as confirmation, not a trigger."
        ),
    }


# --------------------------------------------------------------------------- #
# PURE: federal-award normalization + per-sector aggregation
# --------------------------------------------------------------------------- #
def normalize_award(
    award: Dict[str, Any],
    *,
    sector_lookup=sector_for_ticker,
) -> Optional[Dict[str, Any]]:
    """PURE-ish: normalize one raw USAspending award row into a tidy record.

    Determines the award's GICS sector by, in order: an explicit
    ``sector`` field; the NAICS code via :func:`naics_to_sector`; or a resolved
    ``recipient_ticker`` via ``sector_lookup``. Extracts amount, recipient,
    agency. Returns ``None`` only if the row has no usable dollar amount.

    ``sector_lookup`` is injectable for PURE testing (same contract as
    :func:`normalize_congress_trade`).
    """
    def _f(v: Any) -> float:
        try:
            if v is None or v == "":
                return 0.0
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    amount = _f(
        award.get("Award Amount")
        or award.get("award_amount")
        or award.get("amount")
        or award.get("total_obligation")
    )
    if amount <= 0:
        return None

    # 1) explicit sector, 2) NAICS prefix, 3) recipient ticker lookup.
    sector = normalize_sector_name(award.get("sector"))
    if sector is None:
        sector = naics_to_sector(
            award.get("naics_code")
            or award.get("NAICS Code")
            or award.get("naics")
        )
    if sector is None:
        ticker = str(
            award.get("recipient_ticker") or award.get("ticker") or ""
        ).strip().upper()
        if ticker:
            try:
                sector = normalize_sector_name(sector_lookup(ticker))
            except Exception:  # noqa: BLE001
                sector = None

    return {
        "sector": sector,  # may be None
        "amount": amount,
        "recipient": str(
            award.get("Recipient Name")
            or award.get("recipient_name")
            or award.get("recipient")
            or ""
        ).strip(),
        "agency": str(
            award.get("Awarding Agency")
            or award.get("awarding_agency")
            or award.get("agency")
            or ""
        ).strip(),
        "award_id": str(
            award.get("Award ID") or award.get("award_id") or award.get("id") or ""
        ).strip(),
    }


def aggregate_awards_by_sector(
    awards: List[Dict[str, Any]],
    *,
    sector_lookup=sector_for_ticker,
    top_n: int = 5,
) -> Dict[str, Any]:
    """PURE: aggregate federal contract awards into per-sector value/count.

    For each canonical GICS sector::

        total_value = sum(award amounts)
        count       = number of awards
        top_awards  = the ``top_n`` largest awards (recipient/amount/agency)

    Awards that did not resolve to a sector are bucketed under ``"Unknown"`` so
    nothing is silently dropped. Sectors in the output are ordered by descending
    total value (so the heaviest-spending sector is first).

    Parameters
    ----------
    awards : list of dict
        Raw USAspending rows (see module schema) or already-normalized dicts
        (output of :func:`normalize_award`).
    sector_lookup : callable
        ``ticker -> sector|None``, injected for PURE testing.
    top_n : int, default 5
        How many largest awards to keep per sector.

    Returns
    -------
    dict
        ``{"sectors": {sector: {"total_value", "count", "top_awards":[...]}},
        "n_awards": int, "total_value": float}``.
    """
    top_n = max(0, int(top_n))
    by_sector: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    n_used = 0
    grand_total = 0.0
    for raw in awards or []:
        if "amount" in raw and "sector" in raw and "recipient" in raw:
            rec = raw
        else:
            rec = normalize_award(raw, sector_lookup=sector_lookup)
        if rec is None:
            continue
        sector = rec.get("sector") or "Unknown"
        by_sector[sector].append(rec)
        grand_total += float(rec.get("amount") or 0.0)
        n_used += 1

    sectors_out: Dict[str, Any] = {}
    for sector, recs in by_sector.items():
        recs_sorted = sorted(recs, key=lambda r: float(r.get("amount") or 0.0), reverse=True)
        total_value = sum(float(r.get("amount") or 0.0) for r in recs_sorted)
        top = [
            {
                "recipient": r.get("recipient", ""),
                "amount": round(float(r.get("amount") or 0.0), 2),
                "agency": r.get("agency", ""),
                "award_id": r.get("award_id", ""),
            }
            for r in recs_sorted[:top_n]
        ]
        sectors_out[sector] = {
            "total_value": round(total_value, 2),
            "count": len(recs_sorted),
            "top_awards": top,
        }

    # Order sectors by descending total value for a stable, useful output.
    ordered = dict(
        sorted(sectors_out.items(), key=lambda kv: kv[1]["total_value"], reverse=True)
    )
    return {
        "sectors": ordered,
        "n_awards": n_used,
        "total_value": round(grand_total, 2),
    }


# --------------------------------------------------------------------------- #
# IO functions — the ONLY network-touching code. Never raise; return [].
# --------------------------------------------------------------------------- #
_DEFAULT_USER_AGENT = (
    "Tradeskeebot/1.0 (trading-dashboard; contact: schylermcnally@gmail.com)"
)
_FINNHUB_CONGRESS_URL = "https://finnhub.io/api/v1/stock/congressional-trading"
_USASPENDING_AWARD_URL = (
    "https://api.usaspending.gov/api/v2/search/spending_by_award/"
)
_REQUEST_TIMEOUT = 12.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5
_THROTTLE = 0.15  # conservative spacing between requests


def _user_agent() -> str:
    """Compliant User-Agent from env, with a descriptive fallback."""
    return os.environ.get("SECTOR_ROTATION_USER_AGENT", "").strip() or _DEFAULT_USER_AGENT


def _http_request_json(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Any]:
    """GET/POST JSON with retries + backoff. Returns parsed JSON or ``None``.

    Never raises: a missing ``requests`` dep, network error, rate limit, or
    non-2xx after retries all degrade to ``None``.
    """
    try:
        import requests  # local import keeps the PURE surface import-light
    except Exception as e:  # pragma: no cover - requests is a backend dep
        logger.warning("government IO: requests unavailable: %s", e)
        return None

    hdrs = {"User-Agent": _user_agent(), "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=hdrs,
                timeout=_REQUEST_TIMEOUT,
            )
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.info(
                    "government IO: HTTP %s, backoff %.1fs (attempt %d)",
                    resp.status_code, wait, attempt + 1,
                )
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.info("government IO: HTTP %s for %s", resp.status_code, url)
                return None
            return resp.json()
        except Exception as e:  # noqa: BLE001 - tolerant by contract
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.info(
                "government IO: request error (%s), backoff %.1fs (attempt %d)",
                e, wait, attempt + 1,
            )
            time.sleep(wait)
    return None


def fetch_congressional_trades(
    symbol: str,
    lookback_days: int = 90,
) -> List[Dict[str, Any]]:
    """IO: fetch disclosed congressional trades for ``symbol`` (Finnhub free).

    Hits Finnhub's ``/stock/congressional-trading`` endpoint (per-symbol; free
    tier, 60 req/min). Requires ``FINNHUB_API_KEY`` in the environment — without
    it this returns ``[]`` (no network call). Filters to trades whose **filing
    date** falls within ``lookback_days`` (defaulting wide because of the ~45-day
    disclosure lag), and returns raw trade dicts shaped for
    :func:`normalize_congress_trade` / :func:`aggregate_congress_by_sector`.

    Robustness contract: **never raises.** No key, missing ``requests``, network
    error, rate limit, or unexpected payload all degrade to ``[]``.

    Note the per-symbol nature: callers aggregating by sector will fetch the
    sector-ETF constituents (or a watchlist) and feed the union of results into
    :func:`aggregate_congress_by_sector`.
    """
    try:
        sym = (symbol or "").strip().upper()
        if not sym:
            return []
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            logger.info(
                "fetch_congressional_trades: FINNHUB_API_KEY unset; returning []"
            )
            return []
        lookback_days = max(1, int(lookback_days))
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=lookback_days)

        time.sleep(_THROTTLE)
        data = _http_request_json(
            "GET",
            _FINNHUB_CONGRESS_URL,
            params={
                "symbol": sym,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "token": api_key,
            },
        )
        if not data:
            return []

        # Finnhub returns {"data": [...], "symbol": "..."}.
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []

        out: List[Dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            r = dict(r)
            r.setdefault("symbol", sym)
            # Best-effort filing-date filter (tolerant of key variants).
            fd = _parse_iso_date(r.get("filingDate") or r.get("filing_date"))
            if fd is not None and fd < start:
                continue
            out.append(r)
        return out
    except Exception as e:  # noqa: BLE001 - absolute top-level guard
        logger.warning("fetch_congressional_trades(%s) failed: %s", symbol, e)
        return []


def fetch_contract_awards(
    lookback_days: int = 7,
    *,
    limit: int = 100,
    award_type_codes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """IO: fetch recent federal prime-award contracts (USAspending, free/no-auth).

    POSTs to USAspending's ``spending_by_award`` search for prime contract
    awards whose action date falls in the last ``lookback_days`` days, returning
    up to ``limit`` rows shaped for :func:`normalize_award` /
    :func:`aggregate_awards_by_sector`. USAspending needs no API key.

    Each returned row carries (best-effort) ``Recipient Name``, ``Award Amount``,
    ``naics_code``, ``Awarding Agency``, and ``Award ID``. The recipient->ticker
    resolution is intentionally left to the caller (USAspending exposes recipient
    *names*, not tickers); :func:`normalize_award` falls back to the NAICS->GICS
    map when no ticker is supplied.

    Robustness contract: **never raises.** Missing ``requests``, network error,
    rate limit, or unexpected payload all degrade to ``[]``.
    """
    try:
        lookback_days = max(1, int(lookback_days))
        limit = max(1, min(int(limit), 500))  # USAspending caps page size
        # Prime contract award types (A,B,C,D = the contract family).
        types = award_type_codes or ["A", "B", "C", "D"]

        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=lookback_days)

        body = {
            "filters": {
                "time_period": [
                    {"start_date": start.isoformat(), "end_date": end.isoformat()}
                ],
                "award_type_codes": types,
            },
            "fields": [
                "Award ID",
                "Recipient Name",
                "Award Amount",
                "Awarding Agency",
                "naics_code",
                "Description",
            ],
            "sort": "Award Amount",
            "order": "desc",
            "limit": limit,
            "page": 1,
        }

        time.sleep(_THROTTLE)
        data = _http_request_json("POST", _USASPENDING_AWARD_URL, json_body=body)
        if not data or not isinstance(data, dict):
            return []
        results = data.get("results")
        if not isinstance(results, list):
            return []

        out: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, dict):
                out.append(r)
        return out
    except Exception as e:  # noqa: BLE001 - absolute top-level guard
        logger.warning("fetch_contract_awards() failed: %s", e)
        return []
