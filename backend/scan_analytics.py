"""Wiring layer: turn portfolio holdings + OHLC into analytics blocks.

This is the IO/glue layer that sits between the PURE, deterministic analytics
functions in ``backend/analytics/`` (which never touch the network) and the
portfolio scan in ``portfolio_routes.py``. Everything network-touching lives
here: it pulls adjusted-close OHLC via ``hermes.charlotte.data_fetch.fetch_ohlcv``
(per-process cached, so repeated calls within a scan are cheap) and assembles
the additive ``portfolio_risk`` and per-ticker ``analytics`` blocks.

Design rules honoured here:
- ADJUSTED-close semantics: returns/beta/vol/correlation/VaR/Sharpe/Sortino are
  computed off the ``Adj Close`` column. ATR-based price levels (stop/target)
  use raw OHLC so they line up with SnapTrade's raw ``average_buy_price``.
- COMPLETED BARS ONLY: the most recent (possibly in-progress, e.g. intraday
  today) bar is dropped before any signal/return computation to avoid
  look-ahead. ``fetch_ohlcv`` returns through "now", so the tail bar can be
  partial during market hours.
- DEGRADE GRACEFULLY: a missing OHLC series for one name skips that name; it
  never raises into the scan. Every public entry point is wrapped so analytics
  failures become absent/null fields, not a failed scan.
- ~1-month rolling correlation (21 trading bars), not multi-year.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Annualization + risk constants
_TRADING_DAYS = 252
_RISK_FREE_ANNUAL = 0.045
_CORR_WINDOW = 21          # ~1 trading month
_RISK_PCT = 0.025          # 2.5% fixed-fractional risk per trade (Schyler's default)
_ATR_PERIOD = 14
_ATR_STOP_MULT = 2.0
_ATR_TARGET_MULT = 3.0
_BENCHMARK = "SPY"
_MIN_RETURN_OBS = 20       # need a meaningful sample before reporting beta/vol

# Signal-block parameters
_RSI_PERIOD = 14
_ROC_LOOKBACK = 21         # ~1-month rate-of-change
_RS_LOOKBACK = 63          # ~1-quarter relative-strength vs SPY
_RVOL_WINDOW = 20
_DIVERGENCE_LOOKBACK = 60
_52W_BARS = 252            # trailing 52 weeks of completed daily bars

# Insider-detection parameters
_INSIDER_LOOKBACK_DAYS = 14
_INSIDER_CLUSTER_WINDOW = 7
_INSIDER_MIN_INSIDERS = 2

# Per-process caches so a scan never re-fetches the same symbol's earnings /
# insider data. Cleared naturally on process restart (matching data_fetch).
_EARNINGS_CACHE: Dict[str, Optional[str]] = {}
_INSIDER_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}

# Finnhub earnings-calendar endpoint (IO layer only).
_FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"
_FINNHUB_TIMEOUT = 8.0


def _import_analytics():
    """Import the pure analytics package, handling both run contexts.

    The backend is sometimes run with ``backend/`` on sys.path (so
    ``analytics`` is top-level) and sometimes as ``backend.analytics``.
    """
    try:
        import analytics as A  # type: ignore
        return A
    except Exception:  # pragma: no cover - fallback for package context
        from backend import analytics as A  # type: ignore
        return A


def _fetch_ohlcv(symbol: str, days: int = 420):
    """Cached adjusted OHLCV pull. Returns a DataFrame or None (never raises)."""
    try:
        from hermes.charlotte.data_fetch import fetch_ohlcv
    except Exception:  # pragma: no cover
        try:
            from charlotte.data_fetch import fetch_ohlcv  # type: ignore
        except Exception as e:
            logger.warning(f"scan_analytics: data_fetch unavailable: {e}")
            return None
    try:
        return fetch_ohlcv(symbol, days=days)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scan_analytics: fetch_ohlcv({symbol}) failed: {e}")
        return None


def _completed(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Drop the most recent (possibly in-progress) bar to avoid look-ahead.

    ``fetch_ohlcv`` pulls through 'now'; during market hours the last row is a
    partial bar. We compute everything on completed bars only.
    """
    if df is None or len(df) < 2:
        return None
    return df.iloc[:-1]


def _adj_close(df: pd.DataFrame) -> Optional[pd.Series]:
    col = "Adj Close" if "Adj Close" in df.columns else ("Close" if "Close" in df.columns else None)
    if col is None:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return s if len(s) >= 2 else None


def _daily_returns(adj_close: pd.Series) -> pd.Series:
    return adj_close.pct_change().dropna()


# --------------------------------------------------------------------------- #
# IO helpers for the signals / insider sub-blocks (network-touching, wrapped).
# These are the ONLY network calls added by the signals work; the math itself
# lives in the pure analytics package. All degrade to None/{} on any failure.
# --------------------------------------------------------------------------- #
def _fetch_next_earnings_date(symbol: str) -> Optional[str]:
    """Next scheduled earnings date (ISO ``YYYY-MM-DD``) via Finnhub, or None.

    IO layer only — the pure ``analytics.days_to_earnings`` consumes the date.
    Hits the Finnhub earnings calendar (``FINNHUB_API_KEY`` env) for the window
    [today, today+90d] and returns the soonest upcoming date for ``symbol``.

    Source: https://finnhub.io/docs/api/earnings-calendar
    Never raises: missing key, network error, or empty calendar → ``None``.
    Result is cached per-process so a scan fetches each symbol at most once.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    if sym in _EARNINGS_CACHE:
        return _EARNINGS_CACHE[sym]

    result: Optional[str] = None
    try:
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            logger.debug("scan_analytics: FINNHUB_API_KEY unset; earnings -> None")
            _EARNINGS_CACHE[sym] = None
            return None
        import requests  # local import keeps module import-light

        today = datetime.now(timezone.utc).date()
        params = {
            "symbol": sym,
            "from": today.isoformat(),
            "to": (today + timedelta(days=90)).isoformat(),
            "token": api_key,
        }
        resp = requests.get(
            _FINNHUB_EARNINGS_URL,
            params=params,
            timeout=_FINNHUB_TIMEOUT,
            headers={"User-Agent": _sec_user_agent()},
        )
        resp.raise_for_status()
        rows = (resp.json() or {}).get("earningsCalendar") or []
        # Soonest upcoming (>= today) date wins.
        dates = []
        for r in rows:
            d = str(r.get("date") or "").strip()
            if len(d) == 10:
                try:
                    dd = datetime.strptime(d, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if dd >= today:
                    dates.append(dd)
        if dates:
            result = min(dates).isoformat()
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.info(f"scan_analytics: earnings fetch for {sym} failed: {e}")
        result = None

    _EARNINGS_CACHE[sym] = result
    return result


def _sec_user_agent() -> str:
    """Compliant User-Agent for outbound HTTP (shared by earnings/insider IO).

    Honours ``SEC_EDGAR_USER_AGENT`` (set in app.yaml) so all our outbound
    market-data requests identify the app + a contact, per SEC fair-access and
    general good-citizen practice.
    """
    return (
        os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
        or "trading-dashboard schylermcnally@gmail.com"
    )


def _fetch_insider_block(symbol: str) -> Optional[Dict[str, Any]]:
    """Per-symbol insider-buy sub-block from SEC EDGAR Form-4, or None.

    IO/wiring around the pure ``analytics.insider`` helpers:
    ``fetch_form4`` (the only network call) → ``cluster_buys`` →
    ``score_insider_signal``. Detects open-market buy (code ``P``) clusters of
    >= ``_INSIDER_MIN_INSIDERS`` distinct insiders within ``_INSIDER_CLUSTER_WINDOW``
    days and scores the strongest cluster.

    Never raises; degrades to ``None`` on any failure. Cached per-process.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    if sym in _INSIDER_CACHE:
        return _INSIDER_CACHE[sym]

    block: Optional[Dict[str, Any]] = None
    try:
        A = _import_analytics()
        filings = A.fetch_form4(sym, lookback_days=_INSIDER_LOOKBACK_DAYS)
        buys = A.filter_open_market_buys(filings or [])
        clusters = A.cluster_buys(
            buys,
            window_days=_INSIDER_CLUSTER_WINDOW,
            min_insiders=_INSIDER_MIN_INSIDERS,
        )
        # Pick the strongest cluster (highest scored confidence).
        best: Optional[Dict[str, Any]] = None
        best_score: Optional[Dict[str, Any]] = None
        for c in clusters:
            sc = A.score_insider_signal(c)
            if best_score is None or sc.get("confidence", 0) > best_score.get("confidence", 0):
                best, best_score = c, sc

        block = {
            "open_market_buys": len(buys),
            "has_cluster": bool(clusters),
            "num_clusters": len(clusters),
        }
        if best is not None and best_score is not None:
            block.update(
                {
                    "confidence": best_score.get("confidence"),
                    "bucket": best_score.get("bucket"),
                    "reason": best_score.get("reason"),
                    "num_insiders": best.get("num_insiders"),
                    "total_value": best.get("total_value"),
                    "start_date": best.get("start_date"),
                    "end_date": best.get("end_date"),
                    "insiders": best.get("insiders"),
                }
            )
    except Exception as e:  # noqa: BLE001 - tolerant by contract
        logger.info(f"scan_analytics: insider block for {sym} failed: {e}")
        block = None

    _INSIDER_CACHE[sym] = block
    return block


def _build_signals_block(
    symbol: str,
    df: pd.DataFrame,
    adj: pd.Series,
    *,
    spy_close: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Assemble the per-ticker ``signals`` sub-block from completed bars.

    PURE math is delegated to ``analytics.signals``; this function only marshals
    already-fetched, completed-bar OHLC (``df``/``adj``) and the once-fetched SPY
    adjusted-close series into those functions. Every field is best-effort and
    set to ``None`` when it cannot be computed (no exception escapes).

    Fields: ``rsi``, ``macd`` {macd,signal,hist}, ``divergence``, ``ma_structure``,
    ``roc``, ``relative_strength`` (vs SPY), ``rvol``, ``gap_pct``,
    ``pct_of_52w_range``.
    """
    A = _import_analytics()
    sig: Dict[str, Any] = {}
    close_arr = adj.to_numpy(dtype=float)

    def _f(x: Any) -> Optional[float]:
        try:
            xv = float(x)
            return xv if np.isfinite(xv) else None
        except (TypeError, ValueError):
            return None

    # RSI (Wilder)
    try:
        sig["rsi"] = _f(A.rsi(close_arr, period=_RSI_PERIOD))
    except Exception:  # noqa: BLE001
        sig["rsi"] = None

    # MACD (12/26/9)
    try:
        m = A.macd(close_arr)
        sig["macd"] = {
            "macd": _f(m.get("macd")),
            "signal": _f(m.get("signal")),
            "hist": _f(m.get("hist")),
        }
    except Exception:  # noqa: BLE001
        sig["macd"] = None

    # RSI divergence (price vs RSI series, over the lookback window)
    try:
        rsi_series = A._rsi_series(close_arr, period=_RSI_PERIOD) if hasattr(A, "_rsi_series") else None
        if rsi_series is None:
            from analytics.signals import _rsi_series as _rs  # type: ignore
            rsi_series = _rs(close_arr, period=_RSI_PERIOD)
        div = A.detect_divergence(close_arr, rsi_series, lookback=_DIVERGENCE_LOOKBACK)
        sig["divergence"] = div.get("signal")
    except Exception:  # noqa: BLE001
        sig["divergence"] = None

    # Moving-average structure (50/200 SMA)
    try:
        sig["ma_structure"] = A.ma_structure(close_arr)
    except Exception:  # noqa: BLE001
        sig["ma_structure"] = None

    # Rate-of-change
    try:
        sig["roc"] = _f(A.roc(close_arr, _ROC_LOOKBACK))
    except Exception:  # noqa: BLE001
        sig["roc"] = None

    # Relative strength vs SPY (reuses the once-fetched SPY adjusted close)
    try:
        if spy_close is not None and len(spy_close) >= _RS_LOOKBACK + 1:
            sig["relative_strength"] = _f(
                A.relative_strength(close_arr, spy_close.to_numpy(dtype=float), _RS_LOOKBACK)
            )
        else:
            sig["relative_strength"] = None
    except Exception:  # noqa: BLE001
        sig["relative_strength"] = None

    # Relative volume (raw Volume column)
    try:
        if "Volume" in df.columns:
            vol = pd.to_numeric(df["Volume"], errors="coerce").to_numpy(dtype=float)
            sig["rvol"] = _f(A.rvol(vol, window=_RVOL_WINDOW))
        else:
            sig["rvol"] = None
    except Exception:  # noqa: BLE001
        sig["rvol"] = None

    # Opening gap of the latest completed bar vs the prior completed close
    try:
        if "Open" in df.columns and "Close" in df.columns and len(df) >= 2:
            open_last = _f(pd.to_numeric(df["Open"], errors="coerce").iloc[-1])
            prev_close = _f(pd.to_numeric(df["Close"], errors="coerce").iloc[-2])
            sig["gap_pct"] = (
                _f(A.gap_pct(open_last, prev_close))
                if (open_last is not None and prev_close is not None)
                else None
            )
        else:
            sig["gap_pct"] = None
    except Exception:  # noqa: BLE001
        sig["gap_pct"] = None

    # Position within trailing 52-week range (adjusted high/low)
    try:
        window = adj.tail(_52W_BARS)
        high_52w = _f(window.max())
        low_52w = _f(window.min())
        last = _f(adj.iloc[-1])
        sig["pct_of_52w_range"] = (
            _f(A.pct_of_52w_range(last, high_52w, low_52w))
            if (last is not None and high_52w is not None and low_52w is not None)
            else None
        )
    except Exception:  # noqa: BLE001
        sig["pct_of_52w_range"] = None

    return sig


async def regime_block(spy_close: Optional[pd.Series] = None) -> Optional[Dict[str, Any]]:
    """Payload-level market-regime block (label + size/stop bias). Never raises.

    Thin async wrapper over the exception-wrapped
    ``analytics.regime.get_regime_with_bias`` (which runs the fixed
    ``quant_bridge``). Pass the once-fetched SPY completed-bar adjusted-close
    series so the regime is read off the benchmark without an extra fetch.

    Returns
    -------
    dict or None
        ``{"regime_class", "label", "size_multiplier", "stop_atr_multiplier",
           "note", "raw_state"}`` or ``None`` on any failure.
    """
    try:
        A = _import_analytics()
        prices = None
        if spy_close is not None and len(spy_close) >= 60:
            prices = [float(x) for x in spy_close.to_numpy(dtype=float)]
        res = await A.get_regime_with_bias(prices)
        bias = (res or {}).get("bias") or {}
        state = (res or {}).get("regime_state") or {}
        return {
            "regime_class": bias.get("regime_class"),
            "label": state.get("raw_regime") or state.get("trend_direction"),
            "size_multiplier": bias.get("size_multiplier"),
            "stop_atr_multiplier": bias.get("stop_atr_multiplier"),
            "note": bias.get("note"),
            "trend_direction": state.get("trend_direction"),
            "volatility_regime": state.get("volatility_regime"),
            "estimated_probability": state.get("estimated_probability"),
            "benchmark": _BENCHMARK,
            "used_spy_prices": prices is not None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scan_analytics: regime_block failed: {e}")
        return None


# --------------------------------------------------------------------------- #
# Sector-rotation tagging (additive, exception-wrapped — never breaks a scan)
# --------------------------------------------------------------------------- #
def sector_rotation_tags(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Map each symbol -> its sector's rotation status, keyed by symbol.

    Reuses the daily sector-rotation snapshot (written by the
    ``/api/sector-rotation`` route + digest cron) so a portfolio scan does NOT
    trigger a fresh, slow 5-stream sweep. The pure
    ``sector_rotation.map_to_companies`` does the holding->sector->rotation join;
    ``sector_for_ticker`` (cached, exception-wrapped) resolves each ticker's GICS
    sector.

    Returns ``{SYMBOL: {sector, etf, rotation_score, confidence, status, alert,
    phase, tag}}`` for every symbol that resolves to a scored sector. Symbols with
    no rotation data are simply absent. Never raises — any failure (no snapshot,
    package missing, lookup error) returns ``{}`` so the scan proceeds untagged.

    The snapshot is read from ``SECTOR_ROTATION_SNAPSHOT_PATH`` (default
    ``/tmp/sector_rotation_latest.json``), matching ``sector_rotation_routes``.
    """
    try:
        syms = [str(s).upper().strip() for s in (symbols or []) if str(s).strip()]
        if not syms:
            return {}

        snap_path = os.environ.get(
            "SECTOR_ROTATION_SNAPSHOT_PATH", "/tmp/sector_rotation_latest.json"
        )
        if not os.path.exists(snap_path):
            logger.info("sector_rotation_tags: no snapshot at %s; skipping tags", snap_path)
            return {}
        import json as _json

        with open(snap_path, "r", encoding="utf-8") as f:
            snap = _json.load(f)
        rotation = ((snap or {}).get("result") or {}).get("rotation") or {}
        if not rotation:
            return {}

        from sector_rotation import map_to_companies

        mapped = map_to_companies(rotation, syms)
        out: Dict[str, Dict[str, Any]] = {}
        for row in (mapped or {}).get("tagged", []):
            sym = row.get("symbol")
            # Only attach when we actually have a sector rotation read for it.
            if sym and row.get("status") is not None:
                out[sym] = {
                    "sector": row.get("sector"),
                    "etf": row.get("etf"),
                    "rotation_score": row.get("rotation_score"),
                    "confidence": row.get("confidence"),
                    "status": row.get("status"),
                    "alert": row.get("alert"),
                    "phase": row.get("phase"),
                    "tag": row.get("tag"),
                }
        return out
    except Exception as e:  # noqa: BLE001 - tagging must never break a scan
        logger.warning(f"sector_rotation_tags failed: {e}")
        return {}


# --------------------------------------------------------------------------- #
# Per-ticker analytics block
# --------------------------------------------------------------------------- #
def per_ticker_analytics(
    symbol: str,
    *,
    avg_cost: Optional[float] = None,
    current_price: Optional[float] = None,
    account_value: Optional[float] = None,
    entry_date: Optional[str] = None,
    df: Optional[pd.DataFrame] = None,
    spy_returns: Optional[pd.Series] = None,
    spy_close: Optional[pd.Series] = None,
    include_signals: bool = True,
    include_insider: bool = True,
) -> Optional[Dict[str, Any]]:
    """Build the additive per-ticker ``analytics`` block.

    All fields are best-effort; any sub-metric that cannot be sourced is set to
    ``None`` (and the reason flagged in ``data_gaps``). Returns ``None`` only if
    OHLC is entirely missing (caller omits the block).

    Parameters
    ----------
    symbol : str
    avg_cost : float, optional
        SnapTrade ``average_buy_price`` (raw price space). Drives R-multiple,
        distance-to-stop, unrealized R when present.
    current_price : float, optional
        Latest price (from the scan's quote). Falls back to the last completed
        adjusted close if absent.
    account_value : float, optional
        Total portfolio value, for fixed-fractional position sizing.
    entry_date : str, optional
        ISO entry date. SnapTrade positions do NOT expose this, so it is almost
        always None -> ``days_held`` omitted and flagged.
    df : DataFrame, optional
        Pre-fetched OHLCV (reuses the scan's cached pull). Fetched if None.
    spy_returns : pd.Series, optional
        Completed-bar SPY daily returns for beta. Beta omitted if absent.
    spy_close : pd.Series, optional
        Completed-bar SPY adjusted-close series (fetched once per scan) used for
        the ``signals.relative_strength`` field. Relative strength omitted if
        absent.
    include_signals : bool, default True
        Attach the additive ``signals`` sub-block (RSI/MACD/divergence/MA
        structure/ROC/relative strength/RVOL/gap/52w-range/days-to-earnings).
    include_insider : bool, default True
        Attach the additive ``insider`` sub-block (SEC Form-4 buy clusters).
    """
    try:
        A = _import_analytics()
        if df is None:
            df = _fetch_ohlcv(symbol)
        df = _completed(df)
        if df is None:
            return None

        adj = _adj_close(df)
        if adj is None:
            return None
        rets = _daily_returns(adj)

        data_gaps: List[str] = []
        block: Dict[str, Any] = {
            "as_of_bar": str(adj.index[-1].date()) if hasattr(adj.index[-1], "date") else str(adj.index[-1]),
            "risk_pct_used": _RISK_PCT,
        }

        last_completed_close = float(adj.iloc[-1])
        px = float(current_price) if (current_price and np.isfinite(current_price)) else last_completed_close

        # ATR + ATR-based stop/target (raw OHLC, real-price space to match avg_cost)
        atr_val = None
        try:
            high = pd.to_numeric(df["High"], errors="coerce").to_numpy()
            low = pd.to_numeric(df["Low"], errors="coerce").to_numpy()
            close = pd.to_numeric(df["Close"], errors="coerce").to_numpy()
            atr_val = A.atr(high, low, close, period=_ATR_PERIOD)
            if atr_val is not None and np.isfinite(atr_val):
                # Anchor stop/target on the current price (entry-to-add reference).
                levels = A.atr_levels(
                    px, atr_val,
                    stop_mult=_ATR_STOP_MULT,
                    target_mult=_ATR_TARGET_MULT,
                    direction="long",
                )
                block["atr"] = float(atr_val)
                block["atr_period"] = _ATR_PERIOD
                block["atr_levels"] = {
                    "reference_price": px,
                    "stop": levels["stop"],
                    "target": levels["target"],
                    "stop_mult": _ATR_STOP_MULT,
                    "target_mult": _ATR_TARGET_MULT,
                }
            else:
                atr_val = None
                data_gaps.append("atr_insufficient_bars")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"scan_analytics[{symbol}]: ATR failed: {e}")
            data_gaps.append("atr_error")

        # R-multiple / distance-to-stop / unrealized R — needs entry (avg_cost)
        if avg_cost and np.isfinite(avg_cost) and avg_cost > 0:
            block["entry_price"] = float(avg_cost)
            if atr_val is not None and np.isfinite(atr_val):
                # Stop is placed relative to the ACTUAL entry for R geometry.
                entry_levels = A.atr_levels(
                    float(avg_cost), atr_val,
                    stop_mult=_ATR_STOP_MULT, target_mult=_ATR_TARGET_MULT,
                    direction="long",
                )
                stop = entry_levels["stop"]
                block["stop_from_entry"] = stop
                block["distance_to_stop_pct"] = A.distance_to_stop_pct(float(avg_cost), stop)
                block["unrealized_r"] = A.unrealized_r(px, float(avg_cost), stop)
                block["r_multiple"] = block["unrealized_r"]
                per_share_risk = abs(float(avg_cost) - stop)
                if account_value and np.isfinite(account_value) and account_value > 0:
                    block["suggested_size_shares"] = A.position_size_fixed_fractional(
                        float(account_value), _RISK_PCT, per_share_risk
                    )
                    block["suggested_risk_dollars"] = float(account_value) * _RISK_PCT
                else:
                    data_gaps.append("no_account_value_for_sizing")
            else:
                data_gaps.append("no_atr_for_r_multiple")
        else:
            data_gaps.append("no_entry_avg_cost")

        # Position vol + beta (adjusted returns)
        if len(rets) >= _MIN_RETURN_OBS:
            block["annualized_vol"] = A.position_vol(rets.to_numpy(), _TRADING_DAYS)
            if spy_returns is not None and len(spy_returns) >= _MIN_RETURN_OBS:
                aligned = pd.concat([rets.rename("a"), spy_returns.rename("m")], axis=1, join="inner").dropna()
                if len(aligned) >= _MIN_RETURN_OBS:
                    block["beta_to_spy"] = A.position_beta(
                        aligned["a"].to_numpy(), aligned["m"].to_numpy()
                    )
                else:
                    data_gaps.append("insufficient_overlap_for_beta")
            else:
                data_gaps.append("no_spy_returns_for_beta")
        else:
            data_gaps.append("insufficient_returns")

        # days_held — SnapTrade gives no entry date, so this is almost always absent.
        if entry_date:
            try:
                block["days_held"] = A.days_held(entry_date, pd.Timestamp.utcnow())
            except Exception:
                data_gaps.append("bad_entry_date")
        else:
            data_gaps.append("no_entry_date_available")

        # Additive 'signals' sub-block: technical signals on COMPLETED bars,
        # reusing the already-fetched OHLC (df/adj) and once-fetched SPY series.
        # Fully wrapped: a signals failure never breaks the analytics block.
        if include_signals:
            try:
                signals_block = _build_signals_block(symbol, df, adj, spy_close=spy_close)
                # days_to_earnings: IO (Finnhub) date + pure analytics math.
                try:
                    earn_date = _fetch_next_earnings_date(symbol)
                    signals_block["days_to_earnings"] = A.days_to_earnings(
                        earn_date, pd.Timestamp.utcnow().normalize()
                    )
                    if earn_date is None:
                        data_gaps.append("no_earnings_date")
                except Exception as ee:  # noqa: BLE001
                    signals_block["days_to_earnings"] = None
                    data_gaps.append("earnings_error")
                if spy_close is None:
                    data_gaps.append("no_spy_close_for_relative_strength")
                block["signals"] = signals_block
            except Exception as se:  # noqa: BLE001
                logger.debug(f"scan_analytics[{symbol}]: signals block failed: {se}")
                data_gaps.append("signals_error")

        # Additive 'insider' sub-block: SEC Form-4 open-market buy clusters.
        # Network-touching but fully wrapped + cached; null on any failure.
        if include_insider:
            try:
                ins = _fetch_insider_block(symbol)
                if ins is not None:
                    block["insider"] = ins
                else:
                    data_gaps.append("no_insider_data")
            except Exception as ie:  # noqa: BLE001
                logger.debug(f"scan_analytics[{symbol}]: insider block failed: {ie}")
                data_gaps.append("insider_error")

        if data_gaps:
            block["data_gaps"] = data_gaps
        return block
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scan_analytics: per_ticker_analytics({symbol}) failed: {e}")
        return None


# --------------------------------------------------------------------------- #
# Portfolio-level risk block
# --------------------------------------------------------------------------- #
def portfolio_risk(
    holdings: List[Dict[str, Any]],
    portfolio_value: float,
    *,
    ohlc_cache: Optional[Dict[str, pd.DataFrame]] = None,
) -> Optional[Dict[str, Any]]:
    """Build the additive portfolio-level ``portfolio_risk`` block.

    Parameters
    ----------
    holdings : list of dict
        Each dict needs ``symbol``, ``market_value`` and (optionally) ``sector``.
    portfolio_value : float
        Sum of eligible-equity market values (the scan's ``portfolio_value``).
    ohlc_cache : dict, optional
        Symbol -> completed-bar DataFrame, to reuse the scan's pulls. Anything
        missing is fetched here (per-process cached).

    Returns
    -------
    dict or None
        ``None`` if nothing could be sourced. Otherwise a dict with whatever
        could be computed; sub-blocks that fail are omitted, and ``data_gaps``
        flags what was skipped. Never raises.
    """
    try:
        A = _import_analytics()
        ohlc_cache = ohlc_cache or {}
        data_gaps: List[str] = []

        if not portfolio_value or not np.isfinite(portfolio_value) or portfolio_value <= 0:
            return None

        # 1) gather completed-bar adjusted-close return series per holding
        returns_by_sym: Dict[str, pd.Series] = {}
        weights: Dict[str, float] = {}
        sectors: List[Dict[str, Any]] = []
        skipped: List[str] = []

        for h in holdings:
            sym = str(h.get("symbol") or "").upper()
            mv = float(h.get("market_value") or 0.0)
            if not sym or mv <= 0:
                continue
            df = ohlc_cache.get(sym)
            if df is None:
                df = _completed(_fetch_ohlcv(sym))
            if df is None:
                skipped.append(sym)
                continue
            adj = _adj_close(df)
            if adj is None:
                skipped.append(sym)
                continue
            r = _daily_returns(adj)
            if len(r) < _MIN_RETURN_OBS:
                skipped.append(sym)
                continue
            returns_by_sym[sym] = r
            weights[sym] = mv / portfolio_value
            sectors.append({"sector": h.get("sector") or "Unknown", "weight": mv / portfolio_value})

        if skipped:
            data_gaps.append(f"no_ohlc_for:{','.join(sorted(set(skipped)))}")

        out: Dict[str, Any] = {
            "benchmark": _BENCHMARK,
            "periods_per_year": _TRADING_DAYS,
            "holdings_used": sorted(returns_by_sym.keys()),
            "correlation_window_bars": _CORR_WINDOW,
        }

        # 2) concentration (works off weights alone — always available)
        if weights:
            w_syms = sorted(weights.keys())
            w_arr = np.array([weights[s] for s in w_syms], dtype=float)
            out["hhi"] = A.hhi(w_arr)
            out["effective_number"] = A.effective_number(w_arr)
            out["weights"] = {s: float(weights[s]) for s in w_syms}
        # sector exposure (Unknown unless caller supplied sector — SnapTrade does not)
        if sectors:
            out["sector_exposure"] = A.sector_exposure(sectors)
            if all(s["sector"] == "Unknown" for s in sectors):
                data_gaps.append("no_sector_data")

        # 3) SPY benchmark returns (completed bars)
        spy_df = ohlc_cache.get(_BENCHMARK) or _completed(_fetch_ohlcv(_BENCHMARK))
        spy_rets = None
        if spy_df is not None:
            spy_adj = _adj_close(spy_df)
            if spy_adj is not None:
                spy_rets = _daily_returns(spy_adj)
        if spy_rets is None:
            data_gaps.append("no_spy_benchmark")

        # 4) build an aligned returns frame across holdings (inner join on dates)
        if returns_by_sym:
            frame = pd.DataFrame(returns_by_sym).dropna(how="all")
            # weighted portfolio return series (only over names with data)
            common = frame.dropna()
            if not common.empty:
                used_syms = list(common.columns)
                w_used = np.array([weights[s] for s in used_syms], dtype=float)
                w_norm = w_used / w_used.sum() if w_used.sum() > 0 else w_used
                port_ret = (common[used_syms].to_numpy() @ w_norm)
                port_ret = pd.Series(port_ret, index=common.index)

                out["annualized_vol"] = A.annualized_volatility(port_ret.to_numpy(), _TRADING_DAYS)
                var = A.value_at_risk(port_ret.to_numpy(), conf=0.95)
                out["var_95"] = {
                    "historical": var["historical"],
                    "parametric": var["parametric"],
                    "confidence": 0.95,
                    "horizon": "1d",
                    "units": "fraction_of_portfolio_loss",
                }
                out["sharpe"] = A.sharpe(port_ret.to_numpy(), _RISK_FREE_ANNUAL, _TRADING_DAYS)
                out["sortino"] = A.sortino(port_ret.to_numpy(), 0.0, _TRADING_DAYS)

                # max drawdown from a growth-of-$1 equity curve built from returns
                equity = (1.0 + port_ret).cumprod()
                out["max_drawdown"] = A.max_drawdown(equity.to_numpy())
                out["max_drawdown_note"] = (
                    "synthetic: cumulative product of current-holdings weighted returns, "
                    "NOT realized account equity (true equity history unavailable)"
                )

                # portfolio beta-to-SPY: weighted sum of per-name betas
                if spy_rets is not None:
                    betas = {}
                    for s in used_syms:
                        al = pd.concat(
                            [frame[s].rename("a"), spy_rets.rename("m")], axis=1, join="inner"
                        ).dropna()
                        if len(al) >= _MIN_RETURN_OBS:
                            betas[s] = A.beta(al["a"].to_numpy(), al["m"].to_numpy())
                    if betas:
                        bsum = 0.0
                        wsum = 0.0
                        for s, b in betas.items():
                            if b is not None and np.isfinite(b):
                                bsum += weights[s] * b
                                wsum += weights[s]
                        out["beta_to_spy"] = float(bsum / wsum) if wsum > 0 else None
                        out["per_holding_beta"] = {s: float(b) for s, b in betas.items() if np.isfinite(b)}
            else:
                data_gaps.append("no_common_dates_across_holdings")

            # 5) rolling ~1-month correlation matrix
            if frame.shape[1] >= 2:
                window = frame.tail(_CORR_WINDOW)
                corr = A.correlation_matrix(window)
                # JSON-friendly nested dict, NaN -> None
                corr_clean = corr.where(pd.notnull(corr), None)
                out["correlation_matrix"] = {
                    str(i): {str(j): (None if pd.isna(corr.loc[i, j]) else float(corr.loc[i, j]))
                             for j in corr.columns}
                    for i in corr.index
                }
            else:
                data_gaps.append("need_2plus_holdings_for_correlation")

        if data_gaps:
            out["data_gaps"] = data_gaps

        # Nothing meaningful computed? signal absence.
        if not any(k in out for k in ("annualized_vol", "hhi", "beta_to_spy")):
            return None
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scan_analytics: portfolio_risk failed: {e}")
        return None
