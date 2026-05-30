"""
yfinance-backed option-chain snapshots.

Everything here is deterministic market data — spot, implied vol, expirations
with days-to-expiry, per-expiration expected move, and near-the-money
liquidity. This is the "Python computes" half of the Options Strategist; the
frontend lab and the Claude opportunity finder both consume these snapshots.

yfinance is slow and occasionally flaky, so every call is best-effort, wrapped
in a short TTL cache, and safe to run off the event loop via asyncio.to_thread.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    HAS_YF = True
except Exception:  # pragma: no cover - yfinance always present in requirements
    yf = None
    HAS_YF = False
    logger.warning("yfinance not installed - options chains unavailable")

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:  # pragma: no cover
    np = None
    HAS_NUMPY = False

from . import bs

# Default annual risk-free rate used for Greeks/expected-move when we don't
# fetch a live short-rate. Matches the frontend scenario default (4.5%).
DEFAULT_RISK_FREE = 0.045

# Simple process-local TTL cache. yfinance has no async client and we don't
# want to hammer it during a multi-ticker scan.
_CACHE: Dict[str, tuple[float, Any]] = {}
_SNAPSHOT_TTL = 120.0  # seconds


def _cache_get(key: str) -> Optional[Any]:
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _SNAPSHOT_TTL:
        return hit[1]
    return None


def _cache_put(key: str, value: Any) -> None:
    _CACHE[key] = (time.time(), value)


def _dte(expiry: str) -> float:
    """Calendar days from now (UTC) to an expiration 'YYYY-MM-DD' (4pm ET ≈ 20:00 UTC)."""
    try:
        exp = datetime.strptime(expiry, "%Y-%m-%d").replace(hour=20, tzinfo=timezone.utc)
        delta = (exp - datetime.now(timezone.utc)).total_seconds() / 86400.0
        return max(delta, 0.0)
    except Exception:
        return 0.0


def _historical_vol(closes: List[float], window: int) -> float:
    """Annualized close-to-close realized volatility over the last `window` days."""
    if not HAS_NUMPY or len(closes) < window + 1:
        return 0.0
    arr = np.asarray(closes[-(window + 1):], dtype=float)
    rets = np.diff(np.log(arr))
    if rets.size == 0:
        return 0.0
    return float(np.std(rets, ddof=1) * math.sqrt(252.0))


def _atm_iv(chain, spot: float, T: float, r: float) -> float:
    """ATM implied vol: average of the call & put IV nearest the spot.

    Prefer yfinance's reported impliedVolatility; fall back to solving from the
    mid price when IV is missing/zero (common on thin names).
    """
    ivs: List[float] = []
    for df, opt_type in ((chain.calls, "call"), (chain.puts, "put")):
        if df is None or df.empty:
            continue
        try:
            row = df.iloc[(df["strike"] - spot).abs().argsort().iloc[0]]
        except Exception:
            continue
        iv = float(row.get("impliedVolatility") or 0.0)
        if iv <= 0.0:
            bid = float(row.get("bid") or 0.0)
            ask = float(row.get("ask") or 0.0)
            mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else float(row.get("lastPrice") or 0.0)
            if mid > 0:
                iv = bs.implied_vol(mid, spot, float(row["strike"]), T, r, opt_type)  # type: ignore[arg-type]
        if 0.0 < iv < 5.0:
            ivs.append(iv)
    return sum(ivs) / len(ivs) if ivs else 0.0


def _atm_liquidity(chain, spot: float) -> Dict[str, float]:
    """Open interest + volume on the strikes straddling the spot (a liquidity gauge)."""
    oi = 0.0
    vol = 0.0
    for df in (chain.calls, chain.puts):
        if df is None or df.empty:
            continue
        try:
            near = df.iloc[(df["strike"] - spot).abs().argsort().iloc[:3]]
            oi += float(near["openInterest"].fillna(0).sum())
            vol += float(near["volume"].fillna(0).sum())
        except Exception:
            continue
    return {"open_interest": oi, "volume": vol}


def get_snapshot(symbol: str, *, max_expirations: int = 12) -> Dict[str, Any]:
    """Full deterministic snapshot for one optionable symbol.

    Returns spot, ATM IV (front expiry), realized vol (30d/1y), an IV-rank
    *proxy*, the default risk-free rate, and an expirations table — each with
    days-to-expiry and the ±1σ expected move over that horizon. This is what
    makes the strategist timeframe-aware.

    On any failure returns {"symbol", "error": "..."} rather than raising, so a
    scan over many tickers degrades gracefully.
    """
    symbol = symbol.upper().strip()
    if not HAS_YF:
        return {"symbol": symbol, "error": "yfinance unavailable"}

    cached = _cache_get(f"snap:{symbol}")
    if cached is not None:
        return cached

    try:
        tk = yf.Ticker(symbol)

        # Spot
        spot = 0.0
        try:
            spot = float(tk.fast_info.last_price)
        except Exception:
            pass

        # Historical closes for realized vol
        closes: List[float] = []
        try:
            hist = tk.history(period="1y", auto_adjust=True)
            if hist is not None and not hist.empty:
                closes = [float(c) for c in hist["Close"].dropna().tolist()]
                if spot <= 0 and closes:
                    spot = closes[-1]
        except Exception:
            pass

        if spot <= 0:
            return {"symbol": symbol, "error": "no spot price"}

        hv30 = _historical_vol(closes, 21)
        hv1y = _historical_vol(closes, min(252, max(len(closes) - 1, 2)))

        # Expirations
        try:
            raw_expiries = list(tk.options or [])
        except Exception:
            raw_expiries = []
        if not raw_expiries:
            return {"symbol": symbol, "error": "no listed options"}

        r = DEFAULT_RISK_FREE
        front_iv = 0.0
        expirations: List[Dict[str, Any]] = []

        # Price the front chain in full (for ATM IV + liquidity); for the rest
        # we only need DTE + expected move, which we derive from the front IV.
        for i, exp in enumerate(raw_expiries[:max_expirations]):
            dte = _dte(exp)
            entry: Dict[str, Any] = {
                "date": exp,
                "dte": round(dte, 1),
                "label": _exp_label(dte),
            }
            if i == 0:
                try:
                    chain = tk.option_chain(exp)
                    T = max(dte / 365.0, 1e-6)
                    front_iv = _atm_iv(chain, spot, T, r)
                    entry["atm_iv"] = round(front_iv, 4) if front_iv else None
                    entry["liquidity"] = _atm_liquidity(chain, spot)
                except Exception as e:  # pragma: no cover - network
                    logger.debug("front chain fetch failed for %s %s: %s", symbol, exp, e)
            iv_for_move = front_iv or hv30
            entry["expected_move"] = round(bs.expected_move(spot, iv_for_move, dte), 2)
            if spot > 0 and entry["expected_move"]:
                entry["expected_move_pct"] = round(100.0 * entry["expected_move"] / spot, 2)
            expirations.append(entry)

        atm_iv = front_iv or hv30
        snapshot = {
            "symbol": symbol,
            "spot": round(spot, 2),
            "atm_iv": round(atm_iv, 4) if atm_iv else None,
            "hist_vol_30d": round(hv30, 4) if hv30 else None,
            "hist_vol_1y": round(hv1y, 4) if hv1y else None,
            "iv_premium": round(atm_iv / hv30, 2) if (atm_iv and hv30) else None,
            "iv_rank_proxy": _iv_rank_proxy(atm_iv, hv30, hv1y),
            "risk_free_rate": r,
            "expirations": expirations,
            "asof": datetime.now(timezone.utc).isoformat(),
        }
        _cache_put(f"snap:{symbol}", snapshot)
        return snapshot

    except Exception as e:  # pragma: no cover - network
        logger.warning("snapshot failed for %s: %s", symbol, e)
        return {"symbol": symbol, "error": str(e)}


def _exp_label(dte: float) -> str:
    if dte <= 9:
        return "weekly"
    if dte <= 45:
        return "front-month"
    if dte <= 100:
        return "near-term"
    return "leaps-ish"


def _iv_rank_proxy(atm_iv: float, hv30: float, hv1y: float) -> Optional[int]:
    """A 0-100 IV-rank *proxy*.

    True IV rank needs a year of historical implied vol, which yfinance does
    not expose. We approximate "is volatility cheap or expensive right now" by
    where current ATM IV sits relative to recent (30d) and longer (1y) realized
    vol — the variance-risk-premium lens. Clearly a heuristic; surfaced as
    `iv_rank_proxy` so the UI can label it as such.
    """
    if not atm_iv or not hv30:
        return None
    lo = min(hv30, hv1y or hv30) * 0.7
    hi = max(hv30, hv1y or hv30) * 1.6
    if hi <= lo:
        return 50
    rank = 100.0 * (atm_iv - lo) / (hi - lo)
    return int(max(0, min(100, round(rank))))


def get_chain(symbol: str, expiration: str) -> Dict[str, Any]:
    """Calls/puts for one expiration, enriched with DTE and per-row Greeks.

    Used by the Payoff Lab when the user wants real listed strikes/marks rather
    than the Black-Scholes model price.
    """
    symbol = symbol.upper().strip()
    if not HAS_YF:
        return {"symbol": symbol, "error": "yfinance unavailable"}

    cached = _cache_get(f"chain:{symbol}:{expiration}")
    if cached is not None:
        return cached

    try:
        tk = yf.Ticker(symbol)
        spot = float(tk.fast_info.last_price)
        chain = tk.option_chain(expiration)
        dte = _dte(expiration)
        T = max(dte / 365.0, 1e-6)
        r = DEFAULT_RISK_FREE

        def _rows(df, opt_type: str) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            if df is None or df.empty:
                return out
            for _, row in df.iterrows():
                strike = float(row["strike"])
                iv = float(row.get("impliedVolatility") or 0.0)
                g = bs.price_and_greeks(spot, strike, T, r, iv or 0.0001, opt_type)  # type: ignore[arg-type]
                out.append({
                    "strike": strike,
                    "bid": float(row.get("bid") or 0.0),
                    "ask": float(row.get("ask") or 0.0),
                    "last": float(row.get("lastPrice") or 0.0),
                    "iv": round(iv, 4),
                    "open_interest": int(row.get("openInterest") or 0),
                    "volume": int(row.get("volume") or 0),
                    "delta": round(g["delta"], 4),
                    "in_the_money": bool(row.get("inTheMoney", False)),
                })
            return out

        result = {
            "symbol": symbol,
            "expiration": expiration,
            "dte": round(dte, 1),
            "spot": round(spot, 2),
            "calls": _rows(chain.calls, "call"),
            "puts": _rows(chain.puts, "put"),
        }
        _cache_put(f"chain:{symbol}:{expiration}", result)
        return result

    except Exception as e:  # pragma: no cover - network
        logger.warning("chain fetch failed for %s %s: %s", symbol, expiration, e)
        return {"symbol": symbol, "expiration": expiration, "error": str(e)}
