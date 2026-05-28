#!/usr/bin/env python3
"""NarrativeProjector: forward valuation in the Jeremy Lefebvre / 1000xstocks style.

Story-driven, top-down forward valuation that complements the conservative DCF
layer (`projections.DCFProjector`). Key inputs:
    - Total Addressable Market (TAM) by sector with sector-level CAGR
    - Multi-year time horizon
    - Market capture % (bear/base/bull scenarios)
    - Forward revenue multiple (P/S, bear/base/bull)
    - Shares outstanding to convert market cap → price

Formula:
    future_revenue   = TAM_year_N × capture_pct
    future_marketcap = future_revenue × P/S
    future_price     = future_marketcap / shares_outstanding
    present_value    = future_price / (1 + r) ** N         (r = 12%)

Output: bear/base/bull present-value targets and "x-bagger" multiples vs the
current price.

Public API:
    NarrativeProjector(symbol, horizon_years=5)
        .estimate_tam(sector_overrides=None) -> float (USD billions, future)
        .project_revenue_topdown(capture_pct: float) -> float
        .calculate_narrative_targets(ps_multiples=None, capture_pcts=None) -> dict | None
        .get_summary() -> dict
"""
import os
import sys
from typing import Dict, Optional

import requests

try:
    from hermes.charlotte import data_fetch as df_mod
except ImportError:  # pragma: no cover - exercised in tests via relative layout
    from charlotte import data_fetch as df_mod  # type: ignore


# Sector → (TAM today in USD billions, sector CAGR)
SECTOR_TAM_TABLE: Dict[str, Dict[str, float]] = {
    'Technology':             {'tam_b': 1500.0, 'cagr': 0.18},
    'Healthcare':             {'tam_b': 600.0,  'cagr': 0.08},
    'Consumer Cyclical':      {'tam_b': 500.0,  'cagr': 0.06},
    'Communication Services': {'tam_b': 800.0,  'cagr': 0.10},
    'Financial Services':     {'tam_b': 1000.0, 'cagr': 0.05},
    'Energy':                 {'tam_b': 400.0,  'cagr': 0.04},
    'Industrials':            {'tam_b': 300.0,  'cagr': 0.05},
    'Consumer Defensive':     {'tam_b': 250.0,  'cagr': 0.03},
    'Real Estate':            {'tam_b': 200.0,  'cagr': 0.04},
    'Basic Materials':        {'tam_b': 150.0,  'cagr': 0.03},
    'Utilities':              {'tam_b': 200.0,  'cagr': 0.03},
}
DEFAULT_TAM = {'tam_b': 300.0, 'cagr': 0.06}

NARRATIVE_DISCOUNT_RATE = 0.12

DEFAULT_CAPTURE_PCTS = {'bear': 0.001, 'base': 0.003, 'bull': 0.008}
DEFAULT_PS_MULTIPLES = {'bear': 4.0,   'base': 8.0,   'bull': 15.0}


class NarrativeProjector:
    """Top-down narrative forward valuation (TAM × capture × P/S)."""

    def __init__(self, symbol: str, horizon_years: int = 5):
        self.symbol = symbol.upper()
        self.horizon_years = int(horizon_years)
        self.current_price: Optional[float] = None
        self.shares_outstanding: Optional[float] = None
        self.current_revenue_ttm: Optional[float] = None
        self.sector: Optional[str] = None
        self.industry: Optional[str] = None
        self._load_data()

    # ------------------------------------------------------------------ data
    def _load_data(self) -> None:
        """Populate price, shares, revenue, sector. Best-effort; never raises."""
        finnhub_key = os.environ.get('FINNHUB_API_KEY', '')

        # --- Current price ---
        try:
            ohlcv = df_mod.fetch_ohlcv(self.symbol, days=10)
            if ohlcv is not None and len(ohlcv) > 0:
                self.current_price = float(ohlcv['Close'].iloc[-1])
        except (ValueError, KeyError, AttributeError, ConnectionError, TypeError):
            self.current_price = None

        # --- Finnhub profile (sector, industry, shares) ---
        if finnhub_key:
            try:
                r = requests.get(
                    'https://finnhub.io/api/v1/stock/profile2',
                    params={'symbol': self.symbol, 'token': finnhub_key},
                    timeout=8,
                )
                if r.ok:
                    p = r.json() or {}
                    self.sector = p.get('finnhubIndustry') or p.get('gicsSector')
                    self.industry = p.get('finnhubIndustry')
                    so = p.get('shareOutstanding')
                    if so:
                        # Finnhub reports in millions
                        self.shares_outstanding = float(so) * 1e6
            except (requests.RequestException, ValueError, KeyError):
                pass

        # --- yfinance fallback for sector/shares/revenue ---
        try:
            import yfinance as yf  # type: ignore
            ticker = yf.Ticker(self.symbol)
            info = ticker.info or {}
            if not self.sector:
                self.sector = info.get('sector')
            if not self.industry:
                self.industry = info.get('industry')
            if not self.shares_outstanding:
                so = info.get('sharesOutstanding')
                if so:
                    self.shares_outstanding = float(so)
            if not self.current_price:
                cp = info.get('currentPrice') or info.get('regularMarketPrice')
                if cp:
                    self.current_price = float(cp)
            # TTM revenue: sum last 4 quarterly revenues
            try:
                qf = ticker.quarterly_financials
                if qf is not None and not qf.empty:
                    for label in ('Total Revenue', 'TotalRevenue', 'Revenue'):
                        if label in qf.index:
                            import pandas as pd  # type: ignore
                            vals = [float(x) for x in qf.loc[label].values if pd.notna(x)]
                            if len(vals) >= 4:
                                self.current_revenue_ttm = float(sum(vals[:4]))
                            elif vals:
                                self.current_revenue_ttm = float(vals[0]) * 4
                            break
            except (ValueError, KeyError, AttributeError, ImportError):
                pass
            if not self.current_revenue_ttm:
                rev = info.get('totalRevenue')
                if rev:
                    self.current_revenue_ttm = float(rev)
        except (ImportError, ValueError, KeyError, AttributeError, ConnectionError):
            pass

    # --------------------------------------------------------------- methods
    def estimate_tam(self, sector_overrides: Optional[Dict[str, float]] = None) -> float:
        """Estimate TAM (USD billions) for the horizon year.

        Args:
            sector_overrides: optional dict with keys 'tam_b' and/or 'cagr' to
                force a custom TAM (e.g. {'tam_b': 2000, 'cagr': 0.25} for AI).

        Returns:
            TAM in USD billions, projected ``horizon_years`` into the future.
        """
        base = SECTOR_TAM_TABLE.get(self.sector or '', DEFAULT_TAM)
        tam_today = base['tam_b']
        cagr = base['cagr']
        if sector_overrides:
            tam_today = float(sector_overrides.get('tam_b', tam_today))
            cagr = float(sector_overrides.get('cagr', cagr))
        return tam_today * ((1.0 + cagr) ** self.horizon_years)

    def project_revenue_topdown(self, capture_pct: float) -> float:
        """Return implied future revenue in USD billions for a given capture %."""
        return self.estimate_tam() * float(capture_pct)

    def calculate_narrative_targets(
        self,
        ps_multiples: Optional[Dict[str, float]] = None,
        capture_pcts: Optional[Dict[str, float]] = None,
        sector_overrides: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict]:
        """Compute bear/base/bull present-value price targets.

        Returns ``None`` if essential inputs (current price, shares) are missing.
        """
        if not self.current_price or self.current_price <= 0:
            return None
        if not self.shares_outstanding or self.shares_outstanding <= 0:
            return None

        capture_pcts = capture_pcts or DEFAULT_CAPTURE_PCTS
        ps_multiples = ps_multiples or DEFAULT_PS_MULTIPLES

        tam_future_b = self.estimate_tam(sector_overrides=sector_overrides)
        tam_future_usd = tam_future_b * 1e9
        discount = (1.0 + NARRATIVE_DISCOUNT_RATE) ** self.horizon_years

        future_prices: Dict[str, float] = {}
        pvs: Dict[str, float] = {}
        for scenario in ('bear', 'base', 'bull'):
            cap = float(capture_pcts.get(scenario, DEFAULT_CAPTURE_PCTS[scenario]))
            ps = float(ps_multiples.get(scenario, DEFAULT_PS_MULTIPLES[scenario]))
            future_revenue = tam_future_usd * cap
            future_marketcap = future_revenue * ps
            future_price = future_marketcap / self.shares_outstanding
            future_prices[scenario] = future_price
            pvs[scenario] = future_price / discount

        x_bagger_base = round(future_prices['base'] / self.current_price, 1)
        x_bagger_bull = round(future_prices['bull'] / self.current_price, 1)

        # Pull TAM "today" for the assumptions block
        base_sector = SECTOR_TAM_TABLE.get(self.sector or '', DEFAULT_TAM)
        tam_today = base_sector['tam_b']
        cagr = base_sector['cagr']
        if sector_overrides:
            tam_today = float(sector_overrides.get('tam_b', tam_today))
            cagr = float(sector_overrides.get('cagr', cagr))

        return {
            'bear': round(pvs['bear'], 2),
            'base': round(pvs['base'], 2),
            'bull': round(pvs['bull'], 2),
            'bear_future': round(future_prices['bear'], 2),
            'base_future': round(future_prices['base'], 2),
            'bull_future': round(future_prices['bull'], 2),
            'current_price': round(self.current_price, 2),
            'x_bagger_base': x_bagger_base,
            'x_bagger_bull': x_bagger_bull,
            'horizon_years': self.horizon_years,
            'tam_billions_future': round(tam_future_b, 2),
            'assumptions': {
                'capture_pcts': dict(capture_pcts),
                'ps_multiples': dict(ps_multiples),
                'discount_rate': NARRATIVE_DISCOUNT_RATE,
                'tam_today_b': tam_today,
                'sector_cagr': cagr,
                'sector': self.sector,
            },
        }

    def get_summary(self) -> Dict:
        """Flat dict suitable for logging."""
        targets = self.calculate_narrative_targets()
        base_sector = SECTOR_TAM_TABLE.get(self.sector or '', DEFAULT_TAM)
        tam_today_b = base_sector['tam_b']
        tam_future_b = tam_today_b * ((1.0 + base_sector['cagr']) ** self.horizon_years)

        if targets is None:
            return {
                'symbol': self.symbol,
                'current_price': self.current_price,
                'bear_pv': None,
                'base_pv': None,
                'bull_pv': None,
                'x_bagger_base': None,
                'x_bagger_bull': None,
                'tam_today_b': tam_today_b,
                'tam_future_b': round(tam_future_b, 2),
                'horizon_years': self.horizon_years,
                'sector': self.sector,
            }
        return {
            'symbol': self.symbol,
            'current_price': targets['current_price'],
            'bear_pv': targets['bear'],
            'base_pv': targets['base'],
            'bull_pv': targets['bull'],
            'x_bagger_base': targets['x_bagger_base'],
            'x_bagger_bull': targets['x_bagger_bull'],
            'tam_today_b': tam_today_b,
            'tam_future_b': round(tam_future_b, 2),
            'horizon_years': self.horizon_years,
            'sector': self.sector,
        }
