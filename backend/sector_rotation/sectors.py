"""The SPDR sector-ETF <-> GICS universe (PURE constants + one IO lookup).

The 11 State Street **Select Sector SPDR** ETFs are the de-facto tradable proxy
for the 11 GICS sectors, benchmarked against **SPY** (S&P 500). They are the
backbone of any relative-strength / RRG sector-rotation model: each ETF's price
series vs. SPY gives a clean, liquid measure of how a sector is performing
relative to the broad market.

    ETF    GICS sector                Example holdings
    ----   ------------------------   ---------------------------------------
    XLK    Information Technology     Apple, Microsoft, Nvidia, Meta
    XLF    Financials                 Berkshire, JPMorgan, Bank of America
    XLE    Energy                     ExxonMobil, Chevron, ConocoPhillips
    XLV    Health Care                UnitedHealth, J&J, Eli Lilly
    XLI    Industrials                Boeing, Caterpillar, GE
    XLY    Consumer Discretionary     Amazon, Tesla, Home Depot
    XLP    Consumer Staples           P&G, Walmart, Costco
    XLU    Utilities                  NextEra, Duke, Southern Co.
    XLB    Materials                  Linde, Dow, Nucor
    XLRE   Real Estate                American Tower, Prologis, Weyerhaeuser
    XLC    Communication Services     Alphabet, Disney, Netflix, Comcast
    (SPY)  benchmark (S&P 500)

Layering
--------
- Everything except :func:`sector_for_ticker` is a **PURE constant or pure
  helper** — no network, no disk, deterministic, unit-tested.
- :func:`sector_for_ticker` is the **only IO function**. It maps an *arbitrary*
  ticker (an individual stock, not necessarily an ETF) to its GICS sector via
  yfinance ``.info`` with a Finnhub ``profile2`` fallback. It is cached per
  process, exception-wrapped, and returns ``None`` on any failure — it never
  raises into the caller.

Sources / references
--------------------
- State Street Select Sector SPDRs: https://www.sectorspdrs.com/
- GICS structure (MSCI/S&P): https://www.msci.com/our-solutions/indexes/gics
- yfinance ``Ticker(...).info`` ``sector`` field (uses MSCI-ish names).
- Finnhub ``stock/profile2`` ``finnhubIndustry`` field (free tier).
- Sector-rotation research spec (RRG / data-source design).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PURE constants
# ---------------------------------------------------------------------------

#: Broad-market benchmark all sector ETFs are measured against (RRG/RS).
BENCHMARK = "SPY"

#: Canonical, ordered map of the 11 Select Sector SPDR ETFs to GICS sector
#: names. The sector-name spelling here is the canonical GICS spelling and is
#: the single source of truth for the rest of the package; do not duplicate it.
SECTOR_ETFS: Dict[str, str] = {
    "XLK": "Information Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

#: Reverse map: GICS sector name -> SPDR ETF. Round-trip exact with SECTOR_ETFS.
SECTOR_TO_ETF: Dict[str, str] = {sector: etf for etf, sector in SECTOR_ETFS.items()}

#: Alias of :data:`SECTOR_ETFS` (ETF -> sector), named to read naturally at
#: call sites that already hold an ETF symbol.
ETF_TO_SECTOR: Dict[str, str] = dict(SECTOR_ETFS)

#: Tuple of the 11 ETF symbols, in canonical order (handy for ``yf.download``).
SECTOR_ETF_SYMBOLS = tuple(SECTOR_ETFS.keys())

#: All symbols a rotation scan needs to fetch: the 11 sectors + the benchmark.
ALL_ROTATION_SYMBOLS = SECTOR_ETF_SYMBOLS + (BENCHMARK,)

# Normalization for vendor sector-name variants -> canonical GICS spelling.
# yfinance ``.info["sector"]`` and Finnhub ``finnhubIndustry`` do NOT always use
# the canonical GICS spelling (e.g. yfinance says "Technology" / "Financial
# Services" / "Healthcare"). Map the common variants back so callers always get
# a value that is a key of :data:`SECTOR_TO_ETF`.
_SECTOR_NAME_ALIASES: Dict[str, str] = {
    # yfinance "sector" spellings
    "technology": "Information Technology",
    "information technology": "Information Technology",
    "financial services": "Financials",
    "financial": "Financials",
    "financials": "Financials",
    "healthcare": "Health Care",
    "health care": "Health Care",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "basic materials": "Materials",
    "materials": "Materials",
    "communication services": "Communication Services",
    "communications": "Communication Services",
    "energy": "Energy",
    "industrials": "Industrials",
    "utilities": "Utilities",
    "real estate": "Real Estate",
}


def normalize_sector_name(name: Optional[str]) -> Optional[str]:
    """Map a vendor sector string to the canonical GICS spelling.

    PURE. Case/whitespace-insensitive. Returns the canonical sector name (a key
    of :data:`SECTOR_TO_ETF`) when recognized, otherwise ``None``. Already-canonical
    names pass through unchanged.

    Examples
    --------
    >>> normalize_sector_name("Technology")
    'Information Technology'
    >>> normalize_sector_name("  financial services ")
    'Financials'
    >>> normalize_sector_name("Health Care")
    'Health Care'
    >>> normalize_sector_name("Tobacco") is None
    True
    """
    if not name:
        return None
    key = " ".join(str(name).strip().lower().split())
    if not key:
        return None
    canonical = _SECTOR_NAME_ALIASES.get(key)
    if canonical is not None:
        return canonical
    # Maybe it is already a canonical name with different casing.
    for sector in SECTOR_TO_ETF:
        if sector.lower() == key:
            return sector
    return None


def etf_to_sector(etf: Optional[str]) -> Optional[str]:
    """PURE: SPDR ETF symbol -> GICS sector name, or ``None`` if not a sector ETF.

    Case-insensitive on the symbol.

    >>> etf_to_sector("xlk")
    'Information Technology'
    >>> etf_to_sector("AAPL") is None
    True
    """
    if not etf:
        return None
    return ETF_TO_SECTOR.get(str(etf).strip().upper())


def sector_to_etf(sector: Optional[str]) -> Optional[str]:
    """PURE: GICS sector name -> SPDR ETF symbol, or ``None``.

    Accepts vendor sector-name variants (normalized first).

    >>> sector_to_etf("Technology")
    'XLK'
    >>> sector_to_etf("Real Estate")
    'XLRE'
    """
    canonical = normalize_sector_name(sector)
    if canonical is None:
        # Maybe an exact canonical name was passed (normalize handles that too,
        # but be defensive for names not in the alias table).
        return SECTOR_TO_ETF.get(str(sector).strip()) if sector else None
    return SECTOR_TO_ETF.get(canonical)


def is_sector_etf(symbol: Optional[str]) -> bool:
    """PURE: ``True`` iff ``symbol`` is one of the 11 SPDR sector ETFs."""
    return bool(symbol) and str(symbol).strip().upper() in ETF_TO_SECTOR


# ---------------------------------------------------------------------------
# IO function (the ONLY network-touching code in this module)
# ---------------------------------------------------------------------------

_FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"
_REQUEST_TIMEOUT = 8.0


def _sector_via_yfinance(ticker: str) -> Optional[str]:
    """Best-effort: GICS sector for ``ticker`` via yfinance ``.info``.

    Returns a canonical sector name or ``None``. Never raises. yfinance and its
    transitive deps are imported locally so this module stays import-light and
    so a missing dependency degrades gracefully rather than breaking import.
    """
    try:
        import yfinance as yf  # local import: optional dep, keep module light
    except Exception as e:  # pragma: no cover - dep may be absent in test env
        logger.debug("sector_for_ticker: yfinance unavailable: %s", e)
        return None
    try:
        info = yf.Ticker(ticker).info or {}
        raw = info.get("sector")
        return normalize_sector_name(raw)
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.debug("sector_for_ticker: yfinance lookup failed for %s: %s", ticker, e)
        return None


def _sector_via_finnhub(ticker: str) -> Optional[str]:
    """Fallback: GICS sector for ``ticker`` via Finnhub ``stock/profile2``.

    Uses ``FINNHUB_API_KEY`` from the environment. Returns a canonical sector
    name or ``None`` (no key, network failure, or unrecognized industry all map
    to ``None``). Never raises.
    """
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests  # local import: keeps the pure surface import-light
    except Exception as e:  # pragma: no cover
        logger.debug("sector_for_ticker: requests unavailable: %s", e)
        return None
    try:
        resp = requests.get(
            _FINNHUB_PROFILE_URL,
            params={"symbol": ticker, "token": api_key},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.debug(
                "sector_for_ticker: finnhub HTTP %s for %s", resp.status_code, ticker
            )
            return None
        data = resp.json() or {}
        # profile2 reports the (broad) sector under "finnhubIndustry".
        return normalize_sector_name(data.get("finnhubIndustry"))
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.debug("sector_for_ticker: finnhub lookup failed for %s: %s", ticker, e)
        return None


@lru_cache(maxsize=2048)
def sector_for_ticker(ticker: str) -> Optional[str]:
    """IO: resolve an arbitrary ticker's GICS sector. Cached, never raises.

    For a SPDR sector ETF the answer is returned from the PURE map with no
    network call. For any other ticker (an individual stock), tries yfinance
    ``.info["sector"]`` first, then Finnhub ``stock/profile2`` as a fallback.
    The result is normalized to the canonical GICS spelling (a key of
    :data:`SECTOR_TO_ETF`) or ``None`` if it cannot be determined.

    Cached per process (``lru_cache``) so repeated lookups within a scan do not
    re-hit the network or burn API quota. All failure paths — missing deps, no
    API key, network errors, unknown ticker, unrecognized sector name — degrade
    to ``None``. This function does not raise.

    Parameters
    ----------
    ticker : str
        A stock or ETF symbol (case-insensitive).

    Returns
    -------
    str | None
        Canonical GICS sector name, or ``None`` if undeterminable.
    """
    if not ticker:
        return None
    sym = str(ticker).strip().upper()
    if not sym:
        return None

    # Fast path: a known SPDR sector ETF needs no network call.
    direct = ETF_TO_SECTOR.get(sym)
    if direct is not None:
        return direct

    sector = _sector_via_yfinance(sym)
    if sector is not None:
        return sector
    return _sector_via_finnhub(sym)
