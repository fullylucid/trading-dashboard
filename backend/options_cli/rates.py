"""Risk-free rate for Greeks — 3-month T-bill from FRED, with a safe fallback."""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("options_cli.rates")
_FALLBACK = 0.044  # ~3mo T-bill; only a small input for short-dated Greeks


def risk_free() -> float:
    key = os.getenv("FRED_API_KEY")
    if not key:
        return _FALLBACK
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "DGS3MO", "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": 1},
            timeout=10,
        )
        obs = r.json().get("observations", [])
        if obs and obs[0]["value"] not in (".", ""):
            return float(obs[0]["value"]) / 100.0
    except Exception as e:  # noqa: BLE001
        logger.warning("FRED rate fetch failed (%s); using %.3f", e, _FALLBACK)
    return _FALLBACK
