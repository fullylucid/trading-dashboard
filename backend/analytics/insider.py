"""SEC EDGAR Form-4 insider-BUY detector.

This module detects *open-market insider purchases* (SEC Form-4 transaction
code ``P``) and flags **clusters** — several distinct insiders of the same
issuer buying inside a short window — which historically carry the strongest
bullish signal of the Form-4 transaction codes (see references below).

Layering (mirrors the rest of ``backend/analytics/``):

- **PURE helpers** (no network, no disk, fully unit-testable with crafted
  filing dicts): :func:`filter_open_market_buys`, :func:`cluster_buys`,
  :func:`score_insider_signal`. These take already-fetched "filing dicts" IN
  and return numbers / dicts. They are deterministic given their inputs.
- **IO function**: :func:`fetch_form4` is the *only* network-touching function.
  It hits SEC EDGAR, sends a compliant ``User-Agent``, backs off on rate
  limits/timeouts, parses tolerantly, and returns ``[]`` on any failure
  (it never raises). The dicts it yields are exactly the shape the PURE
  helpers consume.

Filing-dict schema (the contract between IO and PURE layers)::

    {
        "symbol":          "SMCI",        # issuer ticker (uppercased)
        "insider":         "Liang Charles",  # reporting owner display name
        "transaction_code": "P",          # SEC Form-4 code: P/A/M/S/F/G/...
        "transaction_date": "2026-05-12", # YYYY-MM-DD (transaction, not filing)
        "shares":          1000.0,        # transacted shares (best-effort)
        "price":           42.5,          # per-share price (best-effort, may be 0)
        "value":           42500.0,       # shares * price (best-effort)
        "is_director":     True,          # role hints (best-effort)
        "is_officer":      False,
        "officer_title":   "",
        "accession":       "0001193125-26-012345",
    }

Transaction codes (SEC Form-4, Table I/II "Transaction Code"):

==== =========================================================================
Code Meaning
==== =========================================================================
P    **Open-market or private PURCHASE** of securities  (bullish — what we want)
S    Open-market or private sale of securities
A    Grant/award/other acquisition (e.g. RSU vesting) — NOT a market buy
M    Exercise/conversion of derivative (option exercise) — NOT a market buy
F    Payment of exercise price / tax by delivering/withholding securities
G    Bona-fide gift
C    Conversion of derivative security
X    Exercise of in-the-money/at-the-money derivative
==== =========================================================================

Only code ``P`` reflects an insider voluntarily putting their own cash to work
at the prevailing market price, so it is the only code treated as a "buy" here.

Sources / references
--------------------
- SEC EDGAR full-text search:   https://efts.sec.gov/LATEST/search-index
- SEC "fair access" policy (User-Agent required, <=10 req/s):
  https://www.sec.gov/os/webmaster-faq#developers
- Form-4 transaction codes:     https://www.sec.gov/files/forms-3-4-5.pdf
- ``~/.claude/skills/trading-insider-detection`` (reference patterns).
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "filter_open_market_buys",
    "cluster_buys",
    "score_insider_signal",
    "fetch_form4",
    "OPEN_MARKET_BUY_CODE",
]

# The single SEC Form-4 transaction code that represents an open-market /
# private purchase. Everything else (A grant, M exercise, S sell, F tax,
# G gift, ...) is explicitly NOT an insider "buy" for signal purposes.
OPEN_MARKET_BUY_CODE = "P"


# --------------------------------------------------------------------------- #
# PURE helpers — no network, no disk, deterministic. Unit-tested directly.
# --------------------------------------------------------------------------- #
def _norm_code(filing: Dict[str, Any]) -> str:
    """Best-effort extraction of the transaction code from a filing dict.

    Tolerant of key/casing variations seen across parsers
    (``transaction_code`` / ``code`` / ``transactionCode``). Returns the
    upper-cased single-letter code, or ``""`` if absent.
    """
    raw = (
        filing.get("transaction_code")
        or filing.get("code")
        or filing.get("transactionCode")
        or ""
    )
    return str(raw).strip().upper()


def _norm_insider(filing: Dict[str, Any]) -> str:
    """Best-effort, normalised insider identity for distinctness grouping.

    Falls back across common keys and collapses whitespace/case so that
    ``"LIANG  Charles"`` and ``"Liang Charles"`` count as the *same* insider
    when deciding whether a cluster has ``>= min_insiders`` *distinct* buyers.
    """
    raw = (
        filing.get("insider")
        or filing.get("reporting_owner")
        or filing.get("owner")
        or filing.get("name")
        or ""
    )
    return re.sub(r"\s+", " ", str(raw)).strip().upper()


def _parse_date(value: Any) -> Optional[date]:
    """Parse a transaction date that may be a ``date``/``datetime``/ISO string.

    Returns ``None`` if it cannot be parsed (tolerant — bad rows are dropped by
    callers rather than raising).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    # Accept "YYYY-MM-DD", "YYYY-MM-DDTHH:MM:SS", "YYYY/MM/DD".
    s = s.replace("/", "-")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def filter_open_market_buys(filings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep ONLY genuine open-market insider purchases (transaction code ``P``).

    This drops every other Form-4 transaction code — ``A`` (grants/awards),
    ``M`` (option exercises), ``S`` (sells), ``F`` (tax withholding), ``G``
    (gifts), conversions, etc. — because only ``P`` reflects an insider
    voluntarily buying at the market price, which is the bullish tell we score.

    Parameters
    ----------
    filings : list of dict
        Filing dicts (see module docstring for schema). Tolerant of missing
        keys and mixed casing on the transaction-code field.

    Returns
    -------
    list of dict
        The subset of ``filings`` whose transaction code is exactly ``P``.
        Input order is preserved; the input list is not mutated.
    """
    if not filings:
        return []
    return [f for f in filings if _norm_code(f) == OPEN_MARKET_BUY_CODE]


def cluster_buys(
    filings: List[Dict[str, Any]],
    window_days: int = 7,
    min_insiders: int = 2,
) -> List[Dict[str, Any]]:
    """Group open-market buys into per-symbol clusters of distinct insiders.

    A *cluster* is a set of code-``P`` purchases of a single issuer in which at
    least ``min_insiders`` **distinct** insiders each bought within a rolling
    ``window_days`` window. Coordinated buying by several insiders in a short
    span is a materially stronger signal than a lone purchase.

    Algorithm (per symbol):

    1. Filter to open-market buys (defensive — callers may pass raw filings).
    2. Sort that symbol's buys by transaction date (ascending).
    3. Slide an anchor over the buys; for each anchor, take all buys whose date
       is within ``[anchor_date, anchor_date + window_days]`` (inclusive).
    4. If the number of *distinct* insiders in that window is
       ``>= min_insiders``, emit a cluster. Greedily advance the anchor past
       the consumed buys so a long run of buys yields non-overlapping clusters.

    The window is measured in **calendar** days on the transaction date, so a
    7-day window spans e.g. 2026-05-01 .. 2026-05-08 inclusive.

    Parameters
    ----------
    filings : list of dict
        Filing dicts. May contain non-``P`` codes / multiple symbols; both are
        handled here.
    window_days : int, default 7
        Inclusive calendar-day span of the clustering window.
    min_insiders : int, default 2
        Minimum number of DISTINCT insiders required to call it a cluster.

    Returns
    -------
    list of dict
        One dict per detected cluster::

            {
                "symbol":        "SMCI",
                "insiders":      ["LIANG CHARLES", "HSU SARA"],  # distinct, sorted
                "num_insiders":  2,
                "num_buys":      3,
                "start_date":    "2026-05-01",
                "end_date":      "2026-05-06",
                "total_shares":  4000.0,
                "total_value":   170000.0,
                "filings":       [ ...the contributing filing dicts... ],
            }

        Clusters are returned sorted by ``symbol`` then ``start_date``.
    """
    if window_days < 0:
        raise ValueError("window_days must be >= 0")
    if min_insiders < 1:
        raise ValueError("min_insiders must be >= 1")

    buys = filter_open_market_buys(filings)
    if not buys:
        return []

    # Bucket by symbol.
    by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in buys:
        sym = str(f.get("symbol") or "").strip().upper()
        d = _parse_date(f.get("transaction_date") or f.get("date"))
        if not sym or d is None:
            continue  # tolerant: drop rows we cannot place in time/space
        by_symbol[sym].append((d, f))  # type: ignore[arg-type]

    clusters: List[Dict[str, Any]] = []
    span = timedelta(days=window_days)

    for sym in sorted(by_symbol):
        rows = sorted(by_symbol[sym], key=lambda t: t[0])  # by date asc
        i = 0
        n = len(rows)
        while i < n:
            anchor_date = rows[i][0]
            # Collect all buys within [anchor, anchor + window].
            j = i
            window_rows = []
            while j < n and rows[j][0] <= anchor_date + span:
                window_rows.append(rows[j])
                j += 1

            distinct = {_norm_insider(r[1]) for r in window_rows}
            distinct.discard("")  # an unnamed owner does not count toward distinctness

            if len(distinct) >= min_insiders:
                contributing = [r[1] for r in window_rows]
                clusters.append(
                    {
                        "symbol": sym,
                        "insiders": sorted(distinct),
                        "num_insiders": len(distinct),
                        "num_buys": len(window_rows),
                        "start_date": window_rows[0][0].isoformat(),
                        "end_date": window_rows[-1][0].isoformat(),
                        "total_shares": float(
                            sum(_num(f.get("shares")) for f in contributing)
                        ),
                        "total_value": float(
                            sum(_buy_value(f) for f in contributing)
                        ),
                        "filings": contributing,
                    }
                )
                i = j  # non-overlapping: skip past the consumed window
            else:
                i += 1  # slide anchor by one buy

    return clusters


def _num(value: Any) -> float:
    """Tolerant float coercion; non-numeric / missing -> 0.0."""
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _buy_value(filing: Dict[str, Any]) -> float:
    """Dollar value of a buy: explicit ``value`` if present, else shares*price."""
    v = _num(filing.get("value"))
    if v > 0:
        return v
    return _num(filing.get("shares")) * _num(filing.get("price"))


def score_insider_signal(cluster: Dict[str, Any]) -> Dict[str, Any]:
    """Score an insider-buy *cluster* into a 0–100 confidence + bucket.

    Confidence is a transparent weighted sum of features known to matter for
    Form-4 cluster signals (more distinct buyers, more total dollars committed,
    a tighter time window, and C-suite/director involvement all push it up).
    The output bucket follows Tradeskeebot's standard thresholds:

    - ``confidence >= 80``  -> ``"high"``   (immediate-alert grade)
    - ``60 <= confidence < 80`` -> ``"watch"`` (monitor / watchlist)
    - ``confidence < 60``   -> ``"low"``    (log only)

    Scoring (additive, then clamped to [0, 100])::

        base                       = 40                       # any >=2-insider P cluster
        + min(num_insiders - 2, 4) * 12   # each extra distinct buyer (cap +48)
        + dollar_bonus                     # 0 / 6 / 12 / 18 for >$50k/$250k/$1M
        + tightness_bonus                  # +10 if window spans <= 3 calendar days
        + role_bonus                       # +8 if any director/officer involved

    Parameters
    ----------
    cluster : dict
        A cluster dict as produced by :func:`cluster_buys`.

    Returns
    -------
    dict
        ``{"confidence": float (0..100), "bucket": str, "reason": str}``.

    Notes
    -----
    Pure and deterministic — no time-of-day or network dependence. A non-cluster
    (``num_insiders < 2``) scores 0 / ``"low"`` so single-insider noise is not
    promoted.
    """
    num_insiders = int(cluster.get("num_insiders", 0) or 0)
    if num_insiders < 2:
        return {
            "confidence": 0.0,
            "bucket": "low",
            "reason": "not a cluster (fewer than 2 distinct insiders)",
        }

    total_value = _num(cluster.get("total_value"))

    # Window tightness in calendar days.
    start = _parse_date(cluster.get("start_date"))
    end = _parse_date(cluster.get("end_date"))
    span_days = (end - start).days if (start and end) else None

    # Role involvement (best-effort, from contributing filings).
    role_involved = False
    for f in cluster.get("filings", []) or []:
        if f.get("is_director") or f.get("is_officer") or f.get("officer_title"):
            role_involved = True
            break

    score = 40.0
    score += min(num_insiders - 2, 4) * 12.0  # extra distinct buyers, capped

    if total_value >= 1_000_000:
        dollar_bonus = 18.0
    elif total_value >= 250_000:
        dollar_bonus = 12.0
    elif total_value >= 50_000:
        dollar_bonus = 6.0
    else:
        dollar_bonus = 0.0
    score += dollar_bonus

    tightness_bonus = 10.0 if (span_days is not None and span_days <= 3) else 0.0
    score += tightness_bonus

    role_bonus = 8.0 if role_involved else 0.0
    score += role_bonus

    confidence = float(max(0.0, min(100.0, score)))
    bucket = "high" if confidence >= 80 else "watch" if confidence >= 60 else "low"

    parts = [f"{num_insiders} distinct insiders"]
    if total_value > 0:
        parts.append(f"~${total_value:,.0f} bought")
    if span_days is not None:
        parts.append(f"within {span_days}d")
    if role_involved:
        parts.append("director/officer involved")
    reason = "insider buy cluster: " + ", ".join(parts)

    return {"confidence": confidence, "bucket": bucket, "reason": reason}


# --------------------------------------------------------------------------- #
# IO function — the ONLY network-touching code. Never raises; returns [].
# --------------------------------------------------------------------------- #
_DEFAULT_USER_AGENT = "Tradeskeebot/1.0 (trading-dashboard; contact: schylermcnally@gmail.com)"
_EDGAR_FTS_URL = "https://efts.sec.gov/LATEST/search-index"
_REQUEST_TIMEOUT = 10.0   # seconds, per SEC guidance
_MAX_RETRIES = 3
_BACKOFF_BASE = 0.5       # seconds; exponential: 0.5, 1.0, 2.0...
_THROTTLE = 0.12          # >= 0.1s between requests (SEC: <=10 req/s)


def _user_agent() -> str:
    """Compliant SEC User-Agent from env, with a sensible fallback.

    SEC's fair-access policy *requires* a descriptive User-Agent identifying
    the requester (ideally with contact info); requests without one are
    throttled/blocked. Operators should set ``SEC_EDGAR_USER_AGENT``.
    """
    ua = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
    return ua or _DEFAULT_USER_AGENT


def _http_get_json(url: str, params: Dict[str, Any], headers: Dict[str, str]) -> Optional[dict]:
    """GET JSON with retries/backoff. Returns parsed dict or None (never raises)."""
    try:
        import requests  # local import so the pure module stays import-light
    except Exception as e:  # pragma: no cover - requests is a backend dep
        logger.warning("insider.fetch_form4: requests unavailable: %s", e)
        return None

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT
            )
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                # Rate-limited / transient server error -> backoff & retry.
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.info(
                    "insider.fetch_form4: HTTP %s, backing off %.1fs (attempt %d)",
                    resp.status_code, wait, attempt + 1,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 - tolerant by contract
            wait = _BACKOFF_BASE * (2 ** attempt)
            logger.info(
                "insider.fetch_form4: request error (%s), backoff %.1fs (attempt %d)",
                e, wait, attempt + 1,
            )
            time.sleep(wait)
    return None


def _http_get_text(url: str, headers: Dict[str, str]) -> Optional[str]:
    """GET text (a Form-4 XML primary doc) with retries. None on failure."""
    try:
        import requests
    except Exception:  # pragma: no cover
        return None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                time.sleep(_BACKOFF_BASE * (2 ** attempt))
                continue
            resp.raise_for_status()
            return resp.text
        except Exception:  # noqa: BLE001
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    return None


def _xml_findtext(elem, path: str) -> str:
    """Tolerant nested-text getter for the Form-4 XML tree. '' on miss."""
    try:
        found = elem.find(path)
        if found is None:
            return ""
        # Form-4 wraps many scalars in a <value> child.
        val = found.find("value")
        node = val if val is not None else found
        return (node.text or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _parse_form4_xml(xml_text: str, symbol: str, accession: str) -> List[Dict[str, Any]]:
    """Tolerantly parse a Form-4 XML primary document into filing dicts.

    Extracts non-derivative transactions (Table I) and pulls the per-row
    transaction code, date, shares, price, plus the reporting owner's name and
    role flags. Any failure yields ``[]`` for this document — one bad filing
    never poisons the batch.
    """
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
    except Exception as e:  # noqa: BLE001
        logger.info("insider: could not parse Form-4 XML for %s: %s", symbol, e)
        return []

    # Reporting owner (first owner is sufficient for clustering by identity).
    insider = _xml_findtext(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    is_director = is_officer = False
    officer_title = ""
    if rel is not None:
        is_director = (_xml_findtext(rel, "isDirector") in ("1", "true", "True"))
        is_officer = (_xml_findtext(rel, "isOfficer") in ("1", "true", "True"))
        officer_title = _xml_findtext(rel, "officerTitle")

    out: List[Dict[str, Any]] = []
    for txn in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = _xml_findtext(txn, "transactionCoding/transactionCode")
        if not code:
            continue
        txn_date = _xml_findtext(txn, "transactionDate")
        shares = _num(_xml_findtext(txn, "transactionAmounts/transactionShares"))
        price = _num(_xml_findtext(txn, "transactionAmounts/transactionPricePerShare"))
        out.append(
            {
                "symbol": symbol.upper(),
                "insider": insider,
                "transaction_code": code.strip().upper(),
                "transaction_date": txn_date,
                "shares": shares,
                "price": price,
                "value": shares * price,
                "is_director": is_director,
                "is_officer": is_officer,
                "officer_title": officer_title,
                "accession": accession,
            }
        )
    return out


def fetch_form4(symbol: str, lookback_days: int = 14) -> List[Dict[str, Any]]:
    """Fetch recent Form-4 insider transactions for ``symbol`` from SEC EDGAR.

    This is the **only** network-touching function in this module. It:

    1. Queries SEC EDGAR full-text search for form-4 filings of ``symbol`` in
       the last ``lookback_days`` days (compliant ``User-Agent``, retries with
       exponential backoff, throttled to <=10 req/s, 10s timeout).
    2. For each hit, fetches the Form-4 XML primary document and tolerantly
       parses out the per-transaction code / date / shares / price plus the
       reporting owner's identity and role flags.
    3. Returns a flat list of *filing dicts* (see module docstring) — the exact
       shape the PURE helpers (:func:`filter_open_market_buys`,
       :func:`cluster_buys`) consume. Note this returns ALL transaction codes;
       callers filter to ``P`` via :func:`filter_open_market_buys`.

    Robustness contract: **never raises**. Network errors, rate limits, parse
    failures, or a missing ``requests`` dependency all degrade to ``[]``.

    Parameters
    ----------
    symbol : str
        Issuer ticker (e.g. ``"SMCI"``).
    lookback_days : int, default 14
        How many days back to search (by filing date).

    Returns
    -------
    list of dict
        Filing dicts for the matched Form-4 transactions, or ``[]`` on failure.
    """
    try:
        sym = (symbol or "").strip().upper()
        if not sym:
            return []
        lookback_days = max(1, int(lookback_days))

        headers = {
            "User-Agent": _user_agent(),
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Host": "efts.sec.gov",
        }
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=lookback_days)
        params = {
            "q": sym,
            "forms": "4",
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }

        time.sleep(_THROTTLE)
        data = _http_get_json(_EDGAR_FTS_URL, params, headers)
        if not data:
            return []

        hits = (((data or {}).get("hits") or {}).get("hits")) or []
        if not isinstance(hits, list):
            return []

        results: List[Dict[str, Any]] = []
        doc_headers = {
            "User-Agent": _user_agent(),
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        }
        for hit in hits:
            try:
                src = hit.get("_source", {}) if isinstance(hit, dict) else {}
                # _id is "<accession>:<primary_doc>" in full-text search.
                _id = hit.get("_id", "") if isinstance(hit, dict) else ""
                if ":" not in _id:
                    continue
                accession_dashed, primary_doc = _id.split(":", 1)
                accession_nodash = accession_dashed.replace("-", "")
                # CIK of the filer needed to build the archive path.
                ciks = src.get("ciks") or []
                cik = str(ciks[0]).lstrip("0") if ciks else ""
                if not cik or not primary_doc:
                    continue
                doc_url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik}/{accession_nodash}/{primary_doc}"
                )
                time.sleep(_THROTTLE)
                xml_text = _http_get_text(doc_url, doc_headers)
                if not xml_text:
                    continue
                results.extend(_parse_form4_xml(xml_text, sym, accession_dashed))
            except Exception as e:  # noqa: BLE001 - one bad hit must not abort
                logger.info("insider.fetch_form4: skipping a hit for %s: %s", sym, e)
                continue

        return results
    except Exception as e:  # noqa: BLE001 - absolute top-level guard
        logger.warning("insider.fetch_form4(%s) failed: %s", symbol, e)
        return []
