#!/usr/bin/env python3
"""DCF Projections Module for Charlotte Phase 2.

Discounted Cash Flow analysis with:
- Multi-year revenue/earnings projections
- Monte Carlo earnings simulation
- Bull/Base/Bear price target scenarios
- Sensitivity analysis (discount rate × terminal growth)

Public API:
    DCFProjector(symbol, quarters_ahead=12)
        .project_revenue(growth_rates=[0.15, 0.12, 0.10])
        .project_earnings(margin_assumptions=[0.20, 0.22, 0.25])
        .calculate_price_targets(discount_rate=0.08, terminal_growth=0.03)
        .sensitivity_analysis()
"""
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import numpy as np
import pandas as pd
import yfinance as yf

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

try:
    from hermes.charlotte import data_fetch as df_mod
except ImportError:
    from charlotte import data_fetch as df_mod


class DCFProjector:
    """Discounted Cash Flow projector for fundamental analysis.
    
    Attributes:
        symbol (str): Stock ticker
        quarters_ahead (int): Projection horizon (default 12 = 3 years)
        current_price (float): Latest closing price
        current_data (dict): Financials, share count, etc.
    """
    
    def __init__(self, symbol: str, quarters_ahead: int = 12):
        """Initialize projector with live data.
        
        Args:
            symbol: Stock ticker
            quarters_ahead: Number of quarters to project (default 12)
        """
        self.symbol = symbol.upper()
        self.quarters_ahead = quarters_ahead
        self.current_price: Optional[float] = None
        self.current_data: Dict = {}
        self._load_data()
    
    def _load_data(self) -> None:
        """Fetch latest financials, share count, and price from yfinance."""
        try:
            ticker = yf.Ticker(self.symbol)
            info = ticker.info or {}
            
            # Current price
            ohlcv = df_mod.fetch_ohlcv(self.symbol, days=10)
            if ohlcv is not None and len(ohlcv) > 0:
                self.current_price = float(ohlcv['Close'].iloc[-1])
            else:
                self.current_price = float(info.get('currentPrice', 0))
            
            # Quarterly revenue from financials
            qf = ticker.quarterly_financials
            if qf is not None and not qf.empty:
                for label in ('Total Revenue', 'TotalRevenue', 'Revenue'):
                    if label in qf.index:
                        revenues = [float(x) for x in qf.loc[label].values if pd.notna(x)]
                        if revenues:
                            self.current_data['quarterly_revenues'] = revenues[:8]
                            break
            
            # Annual revenues
            af = ticker.financials
            if af is not None and not af.empty:
                for label in ('Total Revenue', 'TotalRevenue', 'Revenue'):
                    if label in af.index:
                        revenues = [float(x) for x in af.loc[label].values if pd.notna(x)]
                        if revenues:
                            self.current_data['annual_revenues'] = revenues[:5]
                            break
            
            # TTM (trailing twelve months) revenue
            if 'quarterly_revenues' in self.current_data and len(self.current_data['quarterly_revenues']) >= 4:
                self.current_data['ttm_revenue'] = sum(self.current_data['quarterly_revenues'][:4])
            elif 'annual_revenues' in self.current_data:
                self.current_data['ttm_revenue'] = self.current_data['annual_revenues'][0]
            
            # EPS and net income
            self.current_data['eps'] = float(info.get('trailingEps', 0))
            self.current_data['net_income'] = float(info.get('netIncomeToCommon', 0))
            
            # Share count
            shares_outstanding = float(info.get('sharesOutstanding', 0))
            if shares_outstanding > 0:
                self.current_data['shares'] = shares_outstanding
            elif self.current_data.get('eps') and self.current_data.get('net_income'):
                self.current_data['shares'] = self.current_data['net_income'] / self.current_data['eps']
            
            # Margins
            self.current_data['operating_margin'] = float(info.get('operatingMargins', 0.15))
            self.current_data['profit_margin'] = float(info.get('profitMargins', 0.10))
            
            # Tax rate (estimate from data or use 20%)
            self.current_data['tax_rate'] = 0.20
            
            # Growth rates (historical 3Y CAGR estimate)
            if 'annual_revenues' in self.current_data and len(self.current_data['annual_revenues']) >= 3:
                revs = np.array(self.current_data['annual_revenues'][:3])
                if revs[0] > 0 and revs[-1] > 0:
                    cagr = (revs[0] / revs[-1]) ** (1/2) - 1
                    self.current_data['historical_growth'] = max(0.0, cagr)
            
        except (ValueError, KeyError, AttributeError, ConnectionError) as e:
            print(f"[{self.symbol}] Data load error: {e}", file=sys.stderr)
    
    def project_revenue(self, growth_rates: List[float] = None) -> Dict:
        """Project annual revenues over 3 years.
        
        Args:
            growth_rates: [Year1 growth%, Year2 growth%, Year3 growth%]
                         Default: [15%, 12%, 10%]
        
        Returns:
            Dict with keys:
                base_year_revenue: Latest full-year revenue
                projections: [year1_rev, year2_rev, year3_rev]
                growth_rates: Input growth assumptions
                cagr_3y: Compound annual growth rate
        """
        if growth_rates is None:
            growth_rates = [0.15, 0.12, 0.10]
        
        # Get base year revenue (TTM or most recent annual)
        base_revenue = self.current_data.get('ttm_revenue') or \
                      (self.current_data.get('annual_revenues', [0])[0] if self.current_data.get('annual_revenues') else 0)
        
        if base_revenue <= 0:
            return {
                'base_year_revenue': 0,
                'projections': [0, 0, 0],
                'growth_rates': growth_rates,
                'cagr_3y': 0,
                'error': 'No revenue data available',
            }
        
        # Project forward
        projections = []
        rev = base_revenue
        for g in growth_rates[:3]:
            rev = rev * (1 + g)
            projections.append(round(rev, 0))
        
        # CAGR
        cagr = (projections[-1] / base_revenue) ** (1/3) - 1 if base_revenue > 0 else 0
        
        return {
            'base_year_revenue': round(base_revenue, 0),
            'projections': projections,
            'growth_rates': growth_rates[:3],
            'cagr_3y': round(cagr, 4),
        }
    
    def project_earnings(self, margin_assumptions: List[float] = None) -> Dict:
        """Project EPS with margins and Monte Carlo simulation.
        
        Args:
            margin_assumptions: [Year1 net margin, Year2, Year3]
                               Default: [20%, 22%, 25%] (percent)
        
        Returns:
            Dict with keys:
                base_year_eps: Current EPS
                projections: [year1_eps, year2_eps, year3_eps]
                margins: Input margin assumptions
                monte_carlo_eps: Mean EPS from 1000 simulations
                eps_std: Std dev of MC simulations
                eps_ci_95: [lower, upper] 95% confidence interval
        """
        if margin_assumptions is None:
            margin_assumptions = [0.20, 0.22, 0.25]
        
        base_eps = self.current_data.get('eps', 0)
        shares = self.current_data.get('shares', 1e9)
        
        if base_eps <= 0:
            return {
                'base_year_eps': 0,
                'projections': [0, 0, 0],
                'margins': margin_assumptions,
                'monte_carlo_eps': 0,
                'eps_std': 0,
                'eps_ci_95': [0, 0],
                'error': 'No EPS data available',
            }
        
        # Get revenue projections
        rev_proj = self.project_revenue()
        rev_base = rev_proj['base_year_revenue']
        rev_forecast = rev_proj['projections']
        
        # Deterministic projections
        eps_projections = []
        for i, margin in enumerate(margin_assumptions[:3]):
            if i < len(rev_forecast) and rev_forecast[i] > 0:
                net_income = rev_forecast[i] * margin
                eps = net_income / shares
                eps_projections.append(round(eps, 4))
            else:
                eps_projections.append(0)
        
        # Monte Carlo: perturb margin assumptions ±200 bps
        n_sims = 1000
        margin_sims = []
        for _ in range(n_sims):
            # Random walk on margins
            sim_margins = []
            for m in margin_assumptions[:3]:
                perturb = np.random.normal(0, 0.02)  # ±2% std dev
                sim_m = max(0.01, m + perturb)
                sim_margins.append(sim_m)
            margin_sims.append(sim_margins)
        
        # For each simulation, compute year3 EPS
        eps_sims = []
        if len(rev_forecast) >= 3 and rev_forecast[2] > 0:
            for margins in margin_sims:
                net_income = rev_forecast[2] * margins[2]
                eps = net_income / shares
                eps_sims.append(eps)
        
        eps_sims = np.array(eps_sims)
        mc_eps = float(np.mean(eps_sims)) if len(eps_sims) > 0 else 0
        eps_std = float(np.std(eps_sims)) if len(eps_sims) > 0 else 0
        ci_lower = float(np.percentile(eps_sims, 2.5)) if len(eps_sims) > 0 else 0
        ci_upper = float(np.percentile(eps_sims, 97.5)) if len(eps_sims) > 0 else 0
        
        return {
            'base_year_eps': round(base_eps, 4),
            'projections': eps_projections,
            'margins': margin_assumptions[:3],
            'monte_carlo_eps': round(mc_eps, 4),
            'eps_std': round(eps_std, 4),
            'eps_ci_95': [round(ci_lower, 4), round(ci_upper, 4)],
        }
    
    def calculate_price_targets(self, discount_rate: float = 0.08, 
                               terminal_growth: float = 0.03) -> Dict:
        """Calculate bull/base/bear price targets via DCF.
        
        Uses Gordon Growth Model:
            PV = FCF_terminal / (discount_rate - terminal_growth)
        
        Args:
            discount_rate: WACC (default 8%)
            terminal_growth: Perpetual growth rate (default 3%)
        
        Returns:
            Dict with keys:
                bull: Upside scenario price target
                base: Base case price target
                bear: Downside scenario price target
                current_price: Latest closing price
                upside: Bull vs. current as percentage string
                breakdown: {scenario: {fcf, pv, price_target}}
        """
        if self.current_price <= 0 or self.current_price is None:
            return {
                'bull': 0, 'base': 0, 'bear': 0,
                'current_price': 0,
                'upside': 'N/A',
                'error': 'No price data',
            }
        
        shares = self.current_data.get('shares', 1e9)
        
        # Get projections for year 3 free cash flow estimate
        rev_proj = self.project_revenue()
        eps_proj = self.project_earnings()
        
        if len(rev_proj['projections']) < 3 or len(eps_proj['projections']) < 3:
            return {
                'bull': 0, 'base': 0, 'bear': 0,
                'current_price': self.current_price,
                'upside': 'N/A',
                'error': 'Insufficient projections',
            }
        
        # FCF ≈ EPS * shares * (1 - capex/revenue) → simplified as EPS * 0.85
        fcf_multiple = 0.85
        
        # Scenarios with margin variations
        scenarios = {
            'bear': {
                'margin_adj': -0.02,  # -200 bps
                'terminal_growth': 0.01,  # 1% terminal
                'discount_rate': discount_rate + 0.02,  # +200 bps
                'fcf_multiple': 0.75,  # Lower FCF conversion
            },
            'base': {
                'margin_adj': 0,
                'terminal_growth': terminal_growth,
                'discount_rate': discount_rate,
                'fcf_multiple': fcf_multiple,
            },
            'bull': {
                'margin_adj': 0.02,  # +200 bps
                'terminal_growth': min(0.05, terminal_growth + 0.02),  # +200 bps
                'discount_rate': discount_rate - 0.01,  # -100 bps
                'fcf_multiple': 0.90,  # Higher FCF conversion
            },
        }
        
        targets = {}
        breakdown = {}
        
        for scenario, params in scenarios.items():
            # Adjust margin for scenario
            adj_margin = eps_proj['margins'][2] + params['margin_adj']
            adj_margin = max(0.01, min(0.50, adj_margin))
            
            # Year 3 revenue projection
            year3_rev = rev_proj['projections'][2]
            
            # Year 3 FCF (simplified)
            year3_fcf = year3_rev * adj_margin * params['fcf_multiple']
            
            # Terminal value (perpetuity)
            tg = params['terminal_growth']
            dr = params['discount_rate']
            
            if dr <= tg:
                # Avoid division issues; cap terminal growth
                tg = max(0.001, dr - 0.01)
            
            terminal_fcf = year3_fcf * (1 + tg)
            terminal_value = terminal_fcf / (dr - tg)
            
            # PV of terminal value (discount back 3 years)
            pv_terminal = terminal_value / ((1 + dr) ** 3)
            
            # Add PV of intermediate FCFs (simplified: assume linear growth to year 3)
            fcf_y1 = year3_rev * (adj_margin - 0.01) * params['fcf_multiple']
            fcf_y2 = year3_rev * (adj_margin - 0.005) * params['fcf_multiple']
            
            pv_fcf = fcf_y1 / (1 + dr) + fcf_y2 / ((1 + dr) ** 2)
            
            # Enterprise value
            enterprise_value = pv_terminal + pv_fcf
            
            # Equity value / price per share
            price_target = enterprise_value / shares if shares > 0 else 0
            
            targets[scenario] = round(price_target, 2)
            breakdown[scenario] = {
                'adj_margin': round(adj_margin, 4),
                'year3_fcf': round(year3_fcf, 0),
                'terminal_value': round(terminal_value, 0),
                'pv_terminal': round(pv_terminal, 0),
                'pv_fcf': round(pv_fcf, 0),
                'enterprise_value': round(enterprise_value, 0),
                'price_target': round(price_target, 2),
            }
        
        # Upside calculation
        bull_target = targets['bull']
        upside_pct = ((bull_target - self.current_price) / self.current_price * 100) if self.current_price > 0 else 0
        upside_str = f"{upside_pct:.1f}%" if upside_pct >= 0 else f"{upside_pct:.1f}%"
        
        return {
            'bull': targets['bull'],
            'base': targets['base'],
            'bear': targets['bear'],
            'current_price': round(self.current_price, 2),
            'upside': upside_str,
            'breakdown': breakdown,
        }
    
    def sensitivity_analysis(self, dr_range: Tuple[float, float] = None,
                            tg_range: Tuple[float, float] = None) -> Dict:
        """Sensitivity analysis: discount_rate × terminal_growth.
        
        Creates a grid of price targets across DR and TG assumptions.
        
        Args:
            dr_range: (min_dr, max_dr), default (0.05, 0.12)
            tg_range: (min_tg, max_tg), default (0.01, 0.05)
        
        Returns:
            Dict with keys:
                discount_rates: Array of tested DRs
                terminal_growths: Array of tested TGs
                sensitivity_grid: 2D array of price targets
                current_price: Reference price
        """
        if dr_range is None:
            dr_range = (0.05, 0.12)
        if tg_range is None:
            tg_range = (0.01, 0.05)
        
        if self.current_price <= 0:
            return {
                'discount_rates': [],
                'terminal_growths': [],
                'sensitivity_grid': [],
                'current_price': 0,
                'error': 'No price data',
            }
        
        shares = self.current_data.get('shares', 1e9)
        rev_proj = self.project_revenue()
        eps_proj = self.project_earnings()
        
        if len(rev_proj['projections']) < 3 or len(eps_proj['projections']) < 3:
            return {
                'discount_rates': [],
                'terminal_growths': [],
                'sensitivity_grid': [],
                'current_price': self.current_price,
                'error': 'Insufficient projections',
            }
        
        # Create grids
        drs = np.linspace(dr_range[0], dr_range[1], 8)
        tgs = np.linspace(tg_range[0], tg_range[1], 8)
        
        year3_rev = rev_proj['projections'][2]
        year3_margin = eps_proj['margins'][2]
        fcf_multiple = 0.85
        
        grid = np.zeros((len(tgs), len(drs)))
        
        for i, tg in enumerate(tgs):
            for j, dr in enumerate(drs):
                if dr <= tg:
                    tg_adj = dr - 0.01
                else:
                    tg_adj = tg
                
                # Simplified FCF calculation
                year3_fcf = year3_rev * year3_margin * fcf_multiple
                terminal_fcf = year3_fcf * (1 + tg_adj)
                terminal_value = terminal_fcf / (dr - tg_adj)
                pv_terminal = terminal_value / ((1 + dr) ** 3)
                
                price_target = pv_terminal / shares if shares > 0 else 0
                grid[i, j] = price_target
        
        return {
            'discount_rates': drs.tolist(),
            'terminal_growths': tgs.tolist(),
            'sensitivity_grid': grid.tolist(),
            'current_price': round(self.current_price, 2),
        }
    
    def get_summary(self) -> Dict:
        """Get complete DCF summary: projections + targets + sensitivity."""
        return {
            'symbol': self.symbol,
            'timestamp': datetime.now().isoformat(),
            'current_price': round(self.current_price, 2) if self.current_price else 0,
            'revenue_projections': self.project_revenue(),
            'earnings_projections': self.project_earnings(),
            'price_targets': self.calculate_price_targets(),
            'sensitivity': self.sensitivity_analysis(),
        }
