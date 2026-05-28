#!/usr/bin/env python3
"""Plotly Chart Builder for Charlotte Phase 2 Projections.

Converts DCFProjector outputs to Plotly JSON charts:
- Revenue waterfall (historical + projected)
- Price paths (bull/base/bear with current price overlay)
- Sensitivity heatmap (discount rate × terminal growth)

Public API:
    PlotlyChartBuilder(projector)
        .plot_revenue_waterfall() → dict (Plotly JSON)
        .plot_price_paths() → dict (Plotly JSON)
        .plot_sensitivity_heatmap() → dict (Plotly JSON)
        .get_all_charts() → dict with all three charts
"""
import sys
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

try:
    from hermes.charlotte.projections import DCFProjector
except ImportError:
    try:
        from charlotte.projections import DCFProjector
    except ImportError:
        from projections import DCFProjector


class PlotlyChartBuilder:
    """Convert DCF projections to Plotly JSON charts."""
    
    def __init__(self, projector: DCFProjector):
        """Initialize with DCFProjector instance.
        
        Args:
            projector: Initialized DCFProjector object
        """
        self.projector = projector
        self.symbol = projector.symbol
    
    def plot_revenue_waterfall(self) -> Dict:
        """Create waterfall chart: historical + projected revenues.
        
        Returns:
            Plotly JSON dict ready for React consumption.
        """
        rev_data = self.projector.project_revenue()
        base_rev = rev_data['base_year_revenue']
        projections = rev_data['projections']
        
        # Gather historical revenues
        historical = self.projector.current_data.get('annual_revenues', [])
        if isinstance(historical, (list, tuple)):
            historical = list(reversed(historical[:5]))  # Oldest to newest
        else:
            historical = []
        
        # X-axis: historical years + 3 projected years
        # Assume current is "2025", historical are "2022", "2023", "2024"
        years = []
        values = []
        colors = []
        
        if len(historical) > 0:
            base_year = 2025 - len(historical)
            for i, h in enumerate(historical):
                years.append(str(base_year + i))
                values.append(h)
                colors.append('#1f77b4')  # Blue for historical
        
        # Add base year if not in historical
        if not historical or historical[-1] != base_rev:
            years.append('2025 (Base)')
            values.append(base_rev)
            colors.append('#1f77b4')
        
        # Add projections
        for i, proj in enumerate(projections):
            years.append(f'2026+{i}Y')
            values.append(proj)
            colors.append('#ff7f0e')  # Orange for projected
        
        # Ensure we have valid data
        if not values or sum(1 for v in values if v > 0) == 0:
            return {
                'error': 'Insufficient revenue data',
                'symbol': self.symbol,
            }
        
        return {
            'data': [
                {
                    'x': years,
                    'y': values,
                    'type': 'bar',
                    'marker': {
                        'color': colors,
                    },
                    'text': [f'${v/1e9:.1f}B' if v >= 1e9 else f'${v/1e6:.0f}M' for v in values],
                    'textposition': 'outside',
                    'name': 'Revenue',
                    'hovertemplate': '%{x}<br>Revenue: %{y:,.0f}<extra></extra>',
                }
            ],
            'layout': {
                'title': f'{self.symbol} Revenue Projection (Historical + Base Case)',
                'xaxis': {'title': 'Year'},
                'yaxis': {'title': 'Revenue ($)'},
                'hovermode': 'x unified',
                'plot_bgcolor': 'rgba(240, 240, 240, 0.5)',
                'paper_bgcolor': 'white',
                'height': 400,
                'showlegend': False,
            },
            'config': {
                'responsive': True,
                'displayModeBar': True,
            },
        }
    
    def plot_price_paths(self) -> Dict:
        """Create line chart: bull/base/bear price paths over 3 years.
        
        Returns:
            Plotly JSON dict with bull/base/bear scenarios + current price overlay.
        """
        targets = self.projector.calculate_price_targets()
        current = targets.get('current_price', 0)
        
        if not current or current <= 0:
            return {
                'error': 'No current price data',
                'symbol': self.symbol,
            }
        
        # Build price paths from current → target over 3 years
        # Quarterly interpolation (12 quarters = 3 years)
        quarters = list(range(0, 13))
        quarter_labels = [f'Q{q % 4 + 1}{2025 + q // 4}' if q > 0 else 'Today' for q in quarters]
        
        scenarios = {
            'bull': targets.get('bull', 0),
            'base': targets.get('base', 0),
            'bear': targets.get('bear', 0),
        }
        
        data = []
        colors = {'bull': '#2ca02c', 'base': '#ff7f0e', 'bear': '#d62728'}
        
        for scenario, target_price in scenarios.items():
            if target_price <= 0:
                continue
            
            # Linear interpolation from current to target
            path = np.linspace(current, target_price, len(quarters))
            
            data.append({
                'x': quarter_labels,
                'y': path.tolist(),
                'type': 'scatter',
                'mode': 'lines+markers',
                'name': scenario.capitalize(),
                'line': {
                    'color': colors[scenario],
                    'width': 2.5,
                },
                'marker': {
                    'size': 4,
                },
                'hovertemplate': '%{x}<br>' + scenario.capitalize() + ': $%{y:.2f}<extra></extra>',
            })
        
        # Add current price horizontal line
        data.append({
            'x': quarter_labels,
            'y': [current] * len(quarter_labels),
            'type': 'scatter',
            'mode': 'lines',
            'name': 'Current Price',
            'line': {
                'color': '#1f77b4',
                'width': 2,
                'dash': 'dash',
            },
            'hovertemplate': 'Current: $%{y:.2f}<extra></extra>',
        })
        
        return {
            'data': data,
            'layout': {
                'title': f'{self.symbol} Price Path Scenarios (3-Year Projection)',
                'xaxis': {
                    'title': 'Timeline',
                },
                'yaxis': {
                    'title': 'Price ($)',
                },
                'hovermode': 'x unified',
                'plot_bgcolor': 'rgba(240, 240, 240, 0.5)',
                'paper_bgcolor': 'white',
                'height': 450,
                'legend': {
                    'x': 0.02,
                    'y': 0.98,
                    'bgcolor': 'rgba(255, 255, 255, 0.8)',
                },
            },
            'config': {
                'responsive': True,
                'displayModeBar': True,
            },
        }
    
    def plot_sensitivity_heatmap(self) -> Dict:
        """Create heatmap: discount_rate × terminal_growth sensitivity.
        
        Returns:
            Plotly JSON heatmap dict showing price target matrix.
        """
        sens = self.projector.sensitivity_analysis()
        
        if 'error' in sens or not sens.get('sensitivity_grid'):
            return {
                'error': 'Insufficient data for sensitivity analysis',
                'symbol': self.symbol,
            }
        
        drs = sens['discount_rates']
        tgs = sens['terminal_growths']
        grid = np.array(sens['sensitivity_grid'])
        
        # Format labels
        dr_labels = [f'{dr*100:.1f}%' for dr in drs]
        tg_labels = [f'{tg*100:.1f}%' for tg in tgs]
        
        # Hover text: show both axes
        hover_text = []
        for i, tg_label in enumerate(tg_labels):
            row = []
            for j, dr_label in enumerate(dr_labels):
                value = grid[i, j]
                row.append(f'DR: {dr_label}<br>TG: {tg_label}<br>Price: ${value:.2f}')
            hover_text.append(row)
        
        return {
            'data': [
                {
                    'z': grid.tolist(),
                    'x': dr_labels,
                    'y': tg_labels,
                    'type': 'heatmap',
                    'colorscale': 'RdYlGn',
                    'colorbar': {
                        'title': 'Price Target ($)',
                    },
                    'text': hover_text,
                    'hovertemplate': '%{text}<extra></extra>',
                    'name': 'Price Target',
                }
            ],
            'layout': {
                'title': f'{self.symbol} DCF Sensitivity Analysis (Discount Rate × Terminal Growth)',
                'xaxis': {
                    'title': 'Discount Rate',
                },
                'yaxis': {
                    'title': 'Terminal Growth Rate',
                },
                'height': 500,
                'plot_bgcolor': 'white',
                'paper_bgcolor': 'white',
            },
            'config': {
                'responsive': True,
                'displayModeBar': True,
            },
        }
    
    def plot_scenario_comparison(self) -> Dict:
        """Create bar chart comparing bull/base/bear price targets + current.
        
        Returns:
            Plotly JSON dict with scenario comparison.
        """
        targets = self.projector.calculate_price_targets()
        current = targets.get('current_price', 0)
        
        if not current or current <= 0:
            return {
                'error': 'No current price data',
                'symbol': self.symbol,
            }
        
        scenarios = ['Bear', 'Base', 'Bull']
        prices = [
            targets.get('bear', 0),
            targets.get('base', 0),
            targets.get('bull', 0),
        ]
        colors = ['#d62728', '#ff7f0e', '#2ca02c']
        
        # Calculate upside/downside % for each
        upside_pcts = [
            ((p - current) / current * 100) if current > 0 else 0
            for p in prices
        ]
        
        return {
            'data': [
                {
                    'x': scenarios,
                    'y': prices,
                    'type': 'bar',
                    'marker': {
                        'color': colors,
                    },
                    'text': [f'${p:.2f}<br>({up:+.1f}%)' for p, up in zip(prices, upside_pcts)],
                    'textposition': 'outside',
                    'name': 'Price Target',
                    'hovertemplate': '%{x}<br>Target: $%{y:.2f}<extra></extra>',
                }
            ],
            'layout': {
                'title': f'{self.symbol} DCF Price Targets (Bull/Base/Bear)',
                'xaxis': {'title': 'Scenario'},
                'yaxis': {'title': 'Price ($)'},
                'shapes': [
                    {
                        'type': 'line',
                        'x0': -0.5,
                        'x1': 2.5,
                        'y0': current,
                        'y1': current,
                        'line': {
                            'color': '#1f77b4',
                            'width': 2,
                            'dash': 'dash',
                        },
                        'name': f'Current: ${current:.2f}',
                    }
                ],
                'height': 400,
                'plot_bgcolor': 'rgba(240, 240, 240, 0.5)',
                'paper_bgcolor': 'white',
                'showlegend': False,
            },
            'config': {
                'responsive': True,
                'displayModeBar': True,
            },
        }
    
    def get_all_charts(self) -> Dict:
        """Return all charts as a single dict: revenue_waterfall, price_paths, sensitivity.
        
        Returns:
            Dict with keys: revenue_waterfall, price_paths, sensitivity, scenario_comparison
        """
        return {
            'symbol': self.symbol,
            'timestamp': pd.Timestamp.now().isoformat(),
            'charts': {
                'revenue_waterfall': self.plot_revenue_waterfall(),
                'price_paths': self.plot_price_paths(),
                'sensitivity_heatmap': self.plot_sensitivity_heatmap(),
                'scenario_comparison': self.plot_scenario_comparison(),
            },
        }
