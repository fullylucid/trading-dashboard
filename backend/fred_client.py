"""
FRED (Federal Reserve Economic Data) client.

Async wrapper over the St. Louis Fed FRED API
(https://fred.stlouisfed.org/docs/api/fred/). Used to surface macro context in
the dashboard: the Treasury yield curve plus a curated set of headline economic
indicators (inflation, labor, growth, rates).

Mirrors the in-memory TTL cache + aiohttp.ClientSession pattern used by
market_data.MarketData so it slots into the same lifespan / cleanup flow. The
API key is read from the FRED_API_KEY environment variable (free key from
https://fredaccount.stlouisfed.org/apikeys).
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# Treasury constant-maturity series, ordered short -> long, keyed by the label
# the frontend renders. The value is the FRED series id (DGS = daily, constant
# maturity, in percent).
TREASURY_SERIES: List[Tuple[str, str]] = [
    ("1M", "DGS1MO"),
    ("3M", "DGS3MO"),
    ("6M", "DGS6MO"),
    ("1Y", "DGS1"),
    ("2Y", "DGS2"),
    ("5Y", "DGS5"),
    ("10Y", "DGS10"),
    ("30Y", "DGS30"),
]

# Curated macro dashboard. ``fred_units`` maps to the FRED ``units`` transform
# applied server-side by FRED:
#   pc1 = percent change from a year ago (YoY)
#   chg = change from the previous observation
# When absent the raw level is returned.
KEY_INDICATORS: List[Dict[str, str]] = [
    {"key": "fed_funds",     "name": "Fed Funds Rate",          "series_id": "FEDFUNDS",        "unit": "%", "category": "Rates"},
    {"key": "treasury_10y",  "name": "10Y Treasury",            "series_id": "DGS10",           "unit": "%", "category": "Rates"},
    {"key": "treasury_2y",   "name": "2Y Treasury",             "series_id": "DGS2",            "unit": "%", "category": "Rates"},
    {"key": "yc_10y_2y",     "name": "10Y-2Y Spread",           "series_id": "T10Y2Y",          "unit": "%", "category": "Rates"},
    {"key": "mortgage_30y",  "name": "30Y Mortgage",            "series_id": "MORTGAGE30US",    "unit": "%", "category": "Rates"},
    {"key": "cpi_yoy",       "name": "CPI (YoY)",               "series_id": "CPIAUCSL", "fred_units": "pc1", "unit": "%", "category": "Inflation"},
    {"key": "core_cpi_yoy",  "name": "Core CPI (YoY)",          "series_id": "CPILFESL", "fred_units": "pc1", "unit": "%", "category": "Inflation"},
    {"key": "pce_yoy",       "name": "PCE (YoY)",               "series_id": "PCEPI",    "fred_units": "pc1", "unit": "%", "category": "Inflation"},
    {"key": "unemployment",  "name": "Unemployment Rate",       "series_id": "UNRATE",          "unit": "%", "category": "Labor"},
    {"key": "payrolls_chg",  "name": "Nonfarm Payrolls (MoM)",  "series_id": "PAYEMS",   "fred_units": "chg", "unit": "K", "category": "Labor"},
    {"key": "jobless_claims", "name": "Initial Jobless Claims", "series_id": "ICSA",            "unit": "", "category": "Labor"},
    {"key": "real_gdp",      "name": "Real GDP (QoQ Ann.)",     "series_id": "A191RL1Q225SBEA", "unit": "%", "category": "Growth"},
    {"key": "industrial",    "name": "Industrial Prod. (YoY)",  "series_id": "INDPRO",   "fred_units": "pc1", "unit": "%", "category": "Growth"},
    {"key": "sentiment",     "name": "Consumer Sentiment",      "series_id": "UMCSENT",         "unit": "", "category": "Growth"},
    {"key": "vix",           "name": "VIX",                     "series_id": "VIXCLS",          "unit": "", "category": "Markets"},
]


class FredError(RuntimeError):
    """Raised when a FRED request fails (upstream non-200 or transport error)."""


class FredNotConfigured(FredError):
    """Raised when FRED_API_KEY is not configured."""


class FredClient:
    """Fetches and caches FRED economic series."""

    def __init__(self, api_key: str = "", cache_ttl_minutes: int = 30):
        self.api_key = api_key or os.getenv("FRED_API_KEY", "")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def initialize(self) -> None:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    async def clear_cache(self) -> None:
        self.cache.clear()
        self.cache_time.clear()
        await self.close()

    # -- cache helpers -------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            ts = self.cache_time.get(key, datetime.min)
            if datetime.now() - ts < self.cache_ttl:
                return self.cache[key]
        return None

    def _cache_put(self, key: str, value: Any) -> None:
        self.cache[key] = value
        self.cache_time[key] = datetime.now()

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """FRED encodes missing observations (holidays, not-yet-released) as '.'."""
        try:
            if value in (None, ".", ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    # -- low-level request ---------------------------------------------------

    async def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured:
            raise FredNotConfigured("FRED_API_KEY not configured")
        await self.initialize()
        query = {"api_key": self.api_key, "file_type": "json", **params}
        try:
            async with self.session.get(
                f"{FRED_BASE_URL}/{endpoint}",
                params=query,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    raise FredError(f"FRED {endpoint} -> HTTP {resp.status}: {body}")
                return await resp.json()
        except aiohttp.ClientError as e:
            raise FredError(f"FRED {endpoint} transport error: {e}") from e

    # -- public API ----------------------------------------------------------

    async def get_observations(
        self,
        series_id: str,
        limit: Optional[int] = None,
        sort_order: str = "desc",
        units: Optional[str] = None,
        observation_start: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Raw observations for a series (list of {date, value} dicts)."""
        cache_key = f"obs:{series_id}:{sort_order}:{limit}:{units}:{observation_start}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, Any] = {"series_id": series_id, "sort_order": sort_order}
        if limit:
            params["limit"] = limit
        if units:
            params["units"] = units
        if observation_start:
            params["observation_start"] = observation_start

        data = await self._request("series/observations", params)
        observations = data.get("observations", [])
        self._cache_put(cache_key, observations)
        return observations

    async def get_latest(
        self, series_id: str, units: Optional[str] = None
    ) -> Dict[str, Any]:
        """Latest valid observation plus change vs the prior valid observation.

        Pulls the most recent handful (descending) so a string of '.' holiday
        gaps doesn't strand us without a value.
        """
        observations = await self.get_observations(
            series_id, limit=12, sort_order="desc", units=units
        )
        valid = [
            (o.get("date"), self._to_float(o.get("value")))
            for o in observations
        ]
        valid = [(d, v) for d, v in valid if v is not None]
        if not valid:
            return {"value": None, "date": None, "change": None, "previous": None}

        date, value = valid[0]
        previous = valid[1][1] if len(valid) > 1 else None
        change = round(value - previous, 4) if previous is not None else None
        return {"value": value, "date": date, "change": change, "previous": previous}

    async def get_treasury_yields(self) -> Dict[str, Dict[str, Any]]:
        """Treasury yield curve as a flat {label: {yield, change, ...}} dict.

        The flat shape matches what the dashboard's Treasury Yields panel
        iterates over (it reads ``data.yield`` per entry), so no wrapper keys.
        """
        cache_key = "treasury_yields"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        results = await asyncio.gather(
            *[self.get_latest(series_id) for _, series_id in TREASURY_SERIES],
            return_exceptions=True,
        )
        curve: Dict[str, Dict[str, Any]] = {}
        for (label, series_id), result in zip(TREASURY_SERIES, results):
            if isinstance(result, Exception):
                logger.warning("Treasury %s (%s) fetch failed: %s", label, series_id, result)
                continue
            if result.get("value") is None:
                continue
            curve[label] = {
                "yield": result["value"],
                "change": result.get("change"),
                "series_id": series_id,
                "date": result.get("date"),
            }
        self._cache_put(cache_key, curve)
        return curve

    async def get_indicators(self) -> Dict[str, Any]:
        """Latest value (+ change) for every curated KEY_INDICATORS series."""
        cache_key = "indicators"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        async def one(ind: Dict[str, str]) -> Dict[str, Any]:
            latest = await self.get_latest(ind["series_id"], units=ind.get("fred_units"))
            return {
                "key": ind["key"],
                "name": ind["name"],
                "series_id": ind["series_id"],
                "category": ind["category"],
                "unit": ind["unit"],
                "value": latest["value"],
                "change": latest["change"],
                "date": latest["date"],
            }

        results = await asyncio.gather(
            *[one(ind) for ind in KEY_INDICATORS], return_exceptions=True
        )
        indicators: List[Dict[str, Any]] = []
        for ind, result in zip(KEY_INDICATORS, results):
            if isinstance(result, Exception):
                logger.warning("Indicator %s fetch failed: %s", ind["series_id"], result)
                continue
            indicators.append(result)

        payload = {
            "indicators": indicators,
            "count": len(indicators),
            "timestamp": datetime.now().isoformat(),
        }
        self._cache_put(cache_key, payload)
        return payload

    async def get_series_info(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Metadata for a series (title, units, frequency, dates)."""
        data = await self._request("series", {"series_id": series_id})
        seriess = data.get("seriess", [])
        return seriess[0] if seriess else None

    async def get_series_history(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        limit: Optional[int] = None,
        units: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Ascending {date, value} history with missing observations dropped."""
        observations = await self.get_observations(
            series_id,
            sort_order="asc",
            observation_start=observation_start,
            limit=limit,
            units=units,
        )
        points = [
            {"date": o.get("date"), "value": self._to_float(o.get("value"))}
            for o in observations
        ]
        return [p for p in points if p["value"] is not None]


# Module-level singleton ----------------------------------------------------

_fred_client: Optional[FredClient] = None


def get_fred_client() -> FredClient:
    """Get or create the shared FredClient (reads FRED_API_KEY from env)."""
    global _fred_client
    if _fred_client is None:
        _fred_client = FredClient(api_key=os.getenv("FRED_API_KEY", ""))
    return _fred_client


async def close_fred_client() -> None:
    """Close the shared FredClient (called from app shutdown)."""
    global _fred_client
    if _fred_client is not None:
        await _fred_client.close()
        _fred_client = None
