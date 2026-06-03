"""Per-constituent contribution: which *stocks* are pulling each sector up/down.

The rest of :mod:`sector_rotation` reasons at the **sector-ETF aggregate** level
(RRG, breadth, sector news). That answers "is Tech rotating in?" but not "*which
names* are driving it?". This module fills that gap.

Approach (free-tier, deterministic)
-----------------------------------
Finnhub's free tier does **not** expose ETF holdings/weights, so we ship a
hand-curated map of each SPDR sector ETF's largest constituents with *approximate*
market-cap weights (:data:`SECTOR_CONSTITUENTS`). Weights are normalized over the
*tracked* basket, so a name's contribution is its share of the tracked move, not
the literal index contribution — good enough to rank "who is pulling the sector".

For each sector we then:

1. Pull each tracked name's **% move including extended hours** — yfinance
   ``fast_info`` (latest pre/post-market price vs the prior regular close), so
   after-hours, overnight, and pre-market moves are counted, not just the regular
   session. Finnhub ``/quote`` ``dp`` is a regular-hours-only fallback.
2. Compute ``contribution = normalized_weight * pct_change`` (in the same units as
   ``pct_change``; multiply by 100 for an approximate basis-points read).
3. Rank the positive contributors (**leaders up**) and negative contributors
   (**laggards / leaders down**), flagging any that are in the user's book.
4. Optionally enrich the top movers with a one-line news/sentiment read (reuses
   the lexicon + Finnhub ``company-news`` fetch from :mod:`media`).

Layering mirrors the rest of the package:

- **PURE** (numpy/stdlib only, unit-tested): :data:`SECTOR_CONSTITUENTS`,
  :func:`normalize_weights`, :func:`contribution_of`, :func:`rank_contributors`,
  :func:`summarize_sector`.
- **IO** (exception-wrapped, rate-limit-compliant, degrade to empty/None, never
  raise): :func:`fetch_quote_pct`, :func:`fetch_mover_news`, and the orchestrator
  :func:`compute_contributors`.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sector_rotation.sectors import ETF_TO_SECTOR, SECTOR_ETF_SYMBOLS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PURE: curated constituent universe
# ---------------------------------------------------------------------------
#
# (symbol, approx_weight) per SPDR sector ETF. Symbols are Finnhub-compatible
# (``.`` class shares as Finnhub spells them). Weights are approximate index
# weights (%) as of ~2024-2025; they need not be exact or sum to 100 — they are
# normalized over whatever is tracked here (see ``normalize_weights``). Ordered
# roughly largest-first for readability. Refresh occasionally as indices drift.
SECTOR_CONSTITUENTS: Dict[str, List[Tuple[str, float]]] = {
    "XLK": [  # Information Technology
        ("NVDA", 15.0), ("AAPL", 14.0), ("MSFT", 13.0), ("AVGO", 5.0),
        ("ORCL", 3.0), ("CRM", 2.6), ("AMD", 2.3), ("ADBE", 2.0),
        ("CSCO", 2.0), ("ACN", 1.9), ("QCOM", 1.7), ("TXN", 1.6),
    ],
    "XLF": [  # Financials
        ("BRK.B", 13.0), ("JPM", 10.0), ("V", 7.5), ("MA", 6.5),
        ("BAC", 4.3), ("WFC", 3.6), ("GS", 2.7), ("MS", 2.5),
        ("AXP", 2.4), ("SPGI", 2.3), ("BLK", 2.1), ("C", 2.0),
    ],
    "XLE": [  # Energy
        ("XOM", 23.0), ("CVX", 17.0), ("COP", 8.0), ("EOG", 4.5),
        ("SLB", 4.0), ("WMB", 3.8), ("MPC", 3.6), ("PSX", 3.3),
        ("OKE", 3.2), ("VLO", 3.0),
    ],
    "XLV": [  # Health Care
        ("LLY", 11.0), ("UNH", 9.0), ("JNJ", 7.0), ("ABBV", 6.0),
        ("MRK", 5.0), ("TMO", 4.0), ("ABT", 3.8), ("ISRG", 3.6),
        ("AMGN", 3.3), ("PFE", 3.0), ("DHR", 2.7),
    ],
    "XLI": [  # Industrials
        ("GE", 5.0), ("CAT", 4.6), ("RTX", 4.2), ("UBER", 3.8),
        ("HON", 3.6), ("UNP", 3.4), ("ETN", 3.3), ("BA", 3.0),
        ("DE", 2.9), ("LMT", 2.6), ("ADP", 2.5),
    ],
    "XLY": [  # Consumer Discretionary
        ("AMZN", 23.0), ("TSLA", 15.0), ("HD", 8.0), ("MCD", 4.5),
        ("BKNG", 4.0), ("LOW", 3.6), ("TJX", 3.4), ("NKE", 3.0),
        ("SBUX", 2.6), ("ORLY", 2.3),
    ],
    "XLP": [  # Consumer Staples
        ("COST", 13.0), ("WMT", 11.0), ("PG", 10.0), ("KO", 8.0),
        ("PEP", 6.0), ("PM", 5.0), ("MO", 4.0), ("MDLZ", 3.5),
        ("CL", 3.2), ("TGT", 2.6),
    ],
    "XLU": [  # Utilities
        ("NEE", 13.0), ("SO", 8.0), ("DUK", 7.0), ("CEG", 6.5),
        ("AEP", 5.0), ("SRE", 4.5), ("D", 4.2), ("EXC", 3.8),
        ("XEL", 3.6), ("PEG", 3.3),
    ],
    "XLB": [  # Materials
        ("LIN", 17.0), ("SHW", 7.0), ("ECL", 5.5), ("APD", 5.0),
        ("FCX", 4.8), ("NEM", 4.2), ("CTVA", 4.0), ("DOW", 3.4),
        ("NUE", 3.2), ("DD", 3.0),
    ],
    "XLRE": [  # Real Estate
        ("PLD", 10.0), ("AMT", 9.0), ("EQIX", 7.0), ("WELL", 6.5),
        ("SPG", 5.0), ("PSA", 4.5), ("O", 4.3), ("CCI", 4.0),
        ("DLR", 4.0), ("CSGP", 3.4),
    ],
    "XLC": [  # Communication Services
        ("META", 21.0), ("GOOGL", 12.0), ("GOOG", 11.0), ("NFLX", 6.0),
        ("TMUS", 4.5), ("DIS", 4.0), ("CMCSA", 3.6), ("VZ", 3.4),
        ("T", 3.2), ("CHTR", 2.4),
    ],
}


# ---------------------------------------------------------------------------
# PURE helpers
# ---------------------------------------------------------------------------

def normalize_weights(
    members: Sequence[Tuple[str, float]],
) -> List[Tuple[str, float]]:
    """PURE: normalize a ``(symbol, weight)`` list so the weights sum to 1.0.

    Non-positive or non-finite weights are dropped. An empty / all-zero input
    yields an empty list (never divides by zero). Order is preserved.

    >>> normalize_weights([("A", 3.0), ("B", 1.0)])
    [('A', 0.75), ('B', 0.25)]
    """
    clean: List[Tuple[str, float]] = []
    total = 0.0
    for sym, w in members or []:
        try:
            wf = float(w)
        except (TypeError, ValueError):
            continue
        if wf > 0 and wf == wf and wf != float("inf"):
            clean.append((str(sym).strip().upper(), wf))
            total += wf
    if total <= 0:
        return []
    return [(sym, wf / total) for sym, wf in clean]


def contribution_of(weight: float, pct_change: Optional[float]) -> Optional[float]:
    """PURE: a constituent's contribution to the (tracked) sector move.

    ``weight`` is the normalized basket weight (0..1); ``pct_change`` is the daily
    percent move (e.g. ``2.5`` for +2.5%). Contribution is ``weight * pct_change``
    in *percent* units (multiply by 100 for approximate basis points). Returns
    ``None`` when the move is unknown so callers can distinguish "flat" from "no
    data".

    >>> round(contribution_of(0.15, 4.0), 3)
    0.6
    >>> contribution_of(0.15, None) is None
    True
    """
    if pct_change is None:
        return None
    try:
        w = float(weight)
        p = float(pct_change)
    except (TypeError, ValueError):
        return None
    if w != w or p != p:  # NaN guard
        return None
    return w * p


def rank_contributors(
    rows: Iterable[Mapping[str, Any]],
    *,
    top_n: int = 5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """PURE: split scored constituent rows into (leaders_up, leaders_down).

    ``rows`` are dicts carrying at least ``contribution`` (float | None). Rows with
    a ``None`` contribution (no quote) are ignored for ranking. ``leaders_up`` are
    the most-positive contributors (descending); ``leaders_down`` the most-negative
    (ascending). Each list is capped at ``top_n``.
    """
    scored = [r for r in rows if r.get("contribution") is not None]
    ups = sorted(
        (r for r in scored if float(r["contribution"]) > 0),
        key=lambda r: float(r["contribution"]),
        reverse=True,
    )
    downs = sorted(
        (r for r in scored if float(r["contribution"]) < 0),
        key=lambda r: float(r["contribution"]),
    )
    n = max(0, int(top_n))
    return [dict(r) for r in ups[:n]], [dict(r) for r in downs[:n]]


def summarize_sector(
    etf: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    top_n: int = 5,
) -> Dict[str, Any]:
    """PURE: assemble one sector's contributor block from scored rows.

    Returns ``{etf, sector, net_contribution, n_up, n_down, breadth, leaders_up,
    leaders_down}``. ``net_contribution`` is the sum of all known contributions
    (a tracked-basket move proxy); ``breadth`` is the share of tracked names that
    were up on the day (0..1, or ``None`` if nothing had a quote).
    """
    etf_u = str(etf).strip().upper()
    known = [r for r in rows if r.get("pct_change") is not None]
    n_up = sum(1 for r in known if float(r["pct_change"]) > 0)
    n_down = sum(1 for r in known if float(r["pct_change"]) < 0)
    net = sum(
        float(r["contribution"]) for r in rows if r.get("contribution") is not None
    )
    breadth = (n_up / len(known)) if known else None
    leaders_up, leaders_down = rank_contributors(rows, top_n=top_n)
    return {
        "etf": etf_u,
        "sector": ETF_TO_SECTOR.get(etf_u),
        "net_contribution": round(net, 4),
        "n_up": n_up,
        "n_down": n_down,
        "n_tracked": len(rows),
        "breadth": round(breadth, 4) if breadth is not None else None,
        "leaders_up": leaders_up,
        "leaders_down": leaders_down,
    }


# ---------------------------------------------------------------------------
# IO: quote + news (exception-wrapped, never raise)
# ---------------------------------------------------------------------------

_FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_REQUEST_TIMEOUT = 6.0
# Politeness spacing between per-name yfinance quote fetches (no hard rate limit,
# but be a good citizen). Override with SECTOR_QUOTE_SPACING (0 in tests).
_QUOTE_SPACING = float(os.environ.get("SECTOR_QUOTE_SPACING", "0.3"))
# Spacing between per-mover Finnhub news fetches — these DO hit the 60 req/min
# free-tier ceiling, so keep ~1.1s. Override with SECTOR_NEWS_SPACING.
_NEWS_SPACING = float(os.environ.get("SECTOR_NEWS_SPACING", "1.1"))


def _finnhub_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "").strip()


def _move_via_yfinance(symbol: str) -> Optional[float]:
    """IO: % move *including* pre/post-market via yfinance ``fast_info``. Never raises.

    ``move = (last_price - previous_close) / previous_close * 100`` where
    ``last_price`` is the latest trade *including extended hours* and
    ``previous_close`` is the prior regular-session close. This captures:
      - pre-market: overnight gap + pre-market move vs yesterday's close,
      - regular hours: the full intraday move,
      - post-market: the full day + after-hours move.
    Returns ``None`` if yfinance is unavailable or the fields are missing/invalid.
    """
    try:
        import yfinance as yf  # local import: optional dep, keep module light
    except Exception as e:  # pragma: no cover - dep may be absent
        logger.debug("constituents: yfinance unavailable: %s", e)
        return None
    try:
        fi = yf.Ticker(str(symbol).strip().upper()).fast_info
        last = getattr(fi, "last_price", None)
        prev = getattr(fi, "previous_close", None)
        if last is None or prev is None:
            return None
        last_f, prev_f = float(last), float(prev)
        if prev_f <= 0 or last_f != last_f or prev_f != prev_f:  # NaN/zero guard
            return None
        return (last_f - prev_f) / prev_f * 100.0
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.debug("constituents: yfinance quote failed for %s: %s", symbol, e)
        return None


def fetch_move_pct(
    symbol: str,
    *,
    api_key: Optional[str] = None,
    use_yfinance: bool = True,
    finnhub_fallback: bool = True,
) -> Optional[float]:
    """IO: extended-hours-aware % move for ``symbol``. Never raises.

    Primary source is yfinance ``fast_info`` (counts after-hours / overnight /
    pre-market). Falls back to Finnhub ``/quote`` (regular-hours only) when
    yfinance yields nothing, so a single flaky source never blanks a name.
    Returns ``None`` only when both sources are unavailable.
    """
    if use_yfinance:
        pct = _move_via_yfinance(symbol)
        if pct is not None:
            return pct
    if finnhub_fallback:
        return fetch_quote_pct(symbol, api_key)
    return None


def fetch_quote_pct(symbol: str, api_key: Optional[str] = None) -> Optional[float]:
    """IO: daily percent change for ``symbol`` via Finnhub ``/quote``. Never raises.

    Returns the ``dp`` (percent change) field, or ``None`` on any failure (no key,
    network error, missing/zero-stale data). A response of all-zeros (Finnhub's
    "unknown symbol" shape) maps to ``None`` rather than a misleading 0.0.
    """
    key = (api_key if api_key is not None else _finnhub_key()).strip()
    if not key or not symbol:
        return None
    try:
        import requests  # local import: keep module import-light
    except Exception as e:  # pragma: no cover
        logger.debug("constituents: requests unavailable: %s", e)
        return None
    try:
        resp = requests.get(
            _FINNHUB_QUOTE_URL,
            params={"symbol": str(symbol).strip().upper(), "token": key},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug("constituents: finnhub HTTP %s for %s", resp.status_code, symbol)
            return None
        data = resp.json() or {}
        # Finnhub returns {c,d,dp,h,l,o,pc,t}. An unknown symbol returns all zeros.
        c, pc = data.get("c"), data.get("pc")
        if (c in (None, 0)) and (pc in (None, 0)):
            return None
        dp = data.get("dp")
        if dp is None:
            return None
        return float(dp)
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.debug("constituents: quote fetch failed for %s: %s", symbol, e)
        return None


def fetch_mover_news(
    symbol: str,
    *,
    lookback_days: int = 2,
    max_headlines: int = 6,
) -> Optional[Dict[str, Any]]:
    """IO: a compact news/sentiment read for one mover. Never raises, may be None.

    Reuses :func:`media.fetch_sector_news` (the Finnhub ``company-news`` fetcher —
    it works for any ticker, not just ETFs) plus the lexicon scorer. Returns
    ``{count, net_tone, label, top_headline}`` or ``None`` if there is no news.
    """
    try:
        from sector_rotation.media import (
            fetch_sector_news,
            score_text,
            _headline_text,
        )
    except Exception as e:  # pragma: no cover
        logger.debug("constituents: media import failed: %s", e)
        return None
    try:
        headlines = fetch_sector_news(str(symbol).strip().upper(), lookback_days=lookback_days)
    except Exception as e:  # noqa: BLE001
        logger.debug("constituents: news fetch failed for %s: %s", symbol, e)
        return None
    if not headlines:
        return None
    headlines = headlines[:max_headlines]
    net = 0
    best_text: Optional[str] = None
    best_abs = -1
    for h in headlines:
        s = score_text(_headline_text(h))
        net += s
        if abs(s) > best_abs:
            best_abs = abs(s)
            best_text = (h.get("headline") if isinstance(h, dict) else None) or best_text
    label = "positive" if net > 0 else "negative" if net < 0 else "neutral"
    return {
        "count": len(headlines),
        "net_tone": net,
        "label": label,
        "top_headline": best_text,
    }


# ---------------------------------------------------------------------------
# IO orchestrator
# ---------------------------------------------------------------------------

def compute_contributors(
    holdings: Optional[Sequence[Any]] = None,
    *,
    watchlist: Optional[Sequence[str]] = None,
    etfs: Optional[Sequence[str]] = None,
    top_n: int = 5,
    with_news: bool = True,
    news_top_movers: int = 3,
) -> Dict[str, Any]:
    """IO: per-sector constituent contributions. Never raises; degrades to empty.

    For every sector ETF in ``etfs`` (default: all 11), pull each tracked
    constituent's daily % move, compute its contribution, and rank leaders
    up/down. The top ``news_top_movers`` movers per sector (by |contribution|) are
    enriched with a news/sentiment read when ``with_news`` is set. Names in the
    user's ``holdings``/``watchlist`` are flagged ``in_portfolio`` / ``in_watchlist``.

    Returns ``{"by_etf": {etf: summary}, "asof_quotes": n, "sources_ok": bool}``.
    """
    api_key = _finnhub_key()
    targets = [str(e).strip().upper() for e in (etfs or SECTOR_ETF_SYMBOLS)]

    book = {
        str((p.get("symbol") if isinstance(p, dict) else p) or "").upper().strip()
        for p in (holdings or [])
    }
    book.discard("")
    watch = {str(w or "").upper().strip() for w in (watchlist or [])}
    watch.discard("")

    by_etf: Dict[str, Any] = {}
    quotes_ok = 0
    quotes_tried = 0

    for etf in targets:
        members = normalize_weights(SECTOR_CONSTITUENTS.get(etf, []))
        rows: List[Dict[str, Any]] = []
        for sym, w in members:
            quotes_tried += 1
            pct = fetch_move_pct(sym, api_key=api_key)  # incl. after-hours/overnight
            if pct is not None:
                quotes_ok += 1
            rows.append(
                {
                    "symbol": sym,
                    "weight": round(w, 4),
                    "pct_change": pct,
                    "contribution": contribution_of(w, pct),
                    "in_portfolio": sym in book,
                    "in_watchlist": sym in watch,
                    "news": None,
                }
            )
            if _QUOTE_SPACING > 0:
                time.sleep(_QUOTE_SPACING)

        summary = summarize_sector(etf, rows, top_n=top_n)

        # Enrich the standout movers (union of top up + top down) with news.
        # News hits Finnhub's rate-limited endpoint, so space these out.
        if with_news and api_key:
            movers = (summary["leaders_up"][:news_top_movers]
                      + summary["leaders_down"][:news_top_movers])
            seen: set = set()
            for m in movers:
                sym = m.get("symbol")
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                m["news"] = fetch_mover_news(sym)
                if _NEWS_SPACING > 0:
                    time.sleep(_NEWS_SPACING)
        by_etf[etf] = summary

    return {
        "by_etf": by_etf,
        "quotes_ok": quotes_ok,
        "quotes_tried": quotes_tried,
        "sources_ok": quotes_ok > 0,
    }
