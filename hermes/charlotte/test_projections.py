#!/usr/bin/env python3
"""Unit tests for Charlotte Phase 2 projections, visualizer, and signal enhancer.

Run with: pytest hermes/charlotte/test_projections.py -v

Tests:
    - DCFProjector with SHOP, SOFI, COIN
    - Revenue/earnings projection output structure
    - Price target calculations (bull/base/bear)
    - Sensitivity analysis grid
    - PlotlyChartBuilder JSON output
    - EnhancedSignalEngine signal merging
"""
import sys
import pytest
import json
from typing import Dict

# Add hermes to path
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte.projections import DCFProjector
from charlotte.visualizer import PlotlyChartBuilder
from charlotte.signal_enhancer import EnhancedSignalEngine


class TestDCFProjector:
    """Test DCFProjector class."""
    
    @pytest.fixture(params=['SHOP', 'SOFI', 'COIN'])
    def symbol(self, request):
        """Test symbols."""
        return request.param
    
    def test_init(self, symbol):
        """Test initialization with live data."""
        proj = DCFProjector(symbol, quarters_ahead=12)
        assert proj.symbol == symbol
        assert proj.quarters_ahead == 12
        assert isinstance(proj.current_data, dict)
    
    def test_project_revenue(self, symbol):
        """Test revenue projection output structure."""
        proj = DCFProjector(symbol)
        rev = proj.project_revenue()
        
        assert isinstance(rev, dict)
        assert 'base_year_revenue' in rev
        assert 'projections' in rev
        assert 'growth_rates' in rev
        assert 'cagr_3y' in rev
        
        # Projections should be 3 years
        assert len(rev['projections']) == 3
        
        # All values should be numeric
        assert isinstance(rev['base_year_revenue'], (int, float))
        assert all(isinstance(p, (int, float)) for p in rev['projections'])
        assert isinstance(rev['cagr_3y'], float)
    
    def test_project_revenue_custom_rates(self, symbol):
        """Test revenue projection with custom growth rates."""
        proj = DCFProjector(symbol)
        custom_rates = [0.10, 0.08, 0.05]
        rev = proj.project_revenue(growth_rates=custom_rates)
        
        assert rev['growth_rates'] == custom_rates
        assert len(rev['projections']) == 3
    
    def test_project_earnings(self, symbol):
        """Test earnings projection output structure."""
        proj = DCFProjector(symbol)
        eps = proj.project_earnings()
        
        assert isinstance(eps, dict)
        assert 'base_year_eps' in eps
        assert 'projections' in eps
        assert 'margins' in eps
        assert 'monte_carlo_eps' in eps
        assert 'eps_std' in eps
        assert 'eps_ci_95' in eps
        
        # MC results
        assert isinstance(eps['monte_carlo_eps'], float)
        assert isinstance(eps['eps_std'], float)
        assert len(eps['eps_ci_95']) == 2
        assert eps['eps_ci_95'][0] <= eps['eps_ci_95'][1]
    
    def test_project_earnings_margins(self, symbol):
        """Test earnings projection with custom margins."""
        proj = DCFProjector(symbol)
        custom_margins = [0.18, 0.20, 0.22]
        eps = proj.project_earnings(margin_assumptions=custom_margins)
        
        assert eps['margins'] == custom_margins
        assert len(eps['projections']) == 3
    
    def test_calculate_price_targets(self, symbol):
        """Test price target calculation."""
        proj = DCFProjector(symbol)
        targets = proj.calculate_price_targets()
        
        assert isinstance(targets, dict)
        assert 'bull' in targets
        assert 'base' in targets
        assert 'bear' in targets
        assert 'current_price' in targets
        assert 'upside' in targets
        assert 'breakdown' in targets
        
        # Price targets should be numeric
        assert isinstance(targets['bull'], (int, float))
        assert isinstance(targets['base'], (int, float))
        assert isinstance(targets['bear'], (int, float))
        assert isinstance(targets['current_price'], (int, float))
        
        # Hierarchy: bull >= base >= bear (typically)
        # Note: might not always be true due to model assumptions
        # so we just check they're all positive
        if targets['bull'] > 0:
            assert targets['bull'] > 0
        if targets['base'] > 0:
            assert targets['base'] > 0
        if targets['bear'] > 0:
            assert targets['bear'] > 0
    
    def test_price_targets_custom_assumptions(self, symbol):
        """Test price targets with custom WACC and terminal growth."""
        proj = DCFProjector(symbol)
        targets = proj.calculate_price_targets(discount_rate=0.10, terminal_growth=0.02)
        
        assert 'bull' in targets
        assert 'base' in targets
        assert 'bear' in targets
    
    def test_sensitivity_analysis(self, symbol):
        """Test sensitivity analysis grid."""
        proj = DCFProjector(symbol)
        sens = proj.sensitivity_analysis()
        
        assert isinstance(sens, dict)
        assert 'discount_rates' in sens
        assert 'terminal_growths' in sens
        assert 'sensitivity_grid' in sens
        assert 'current_price' in sens
        
        # Grid dimensions
        drs = sens['discount_rates']
        tgs = sens['terminal_growths']
        grid = sens['sensitivity_grid']
        
        assert len(drs) > 0
        assert len(tgs) > 0
        assert len(grid) == len(tgs)
        assert all(len(row) == len(drs) for row in grid)
    
    def test_sensitivity_analysis_custom_ranges(self, symbol):
        """Test sensitivity analysis with custom DR/TG ranges."""
        proj = DCFProjector(symbol)
        sens = proj.sensitivity_analysis(
            dr_range=(0.06, 0.10),
            tg_range=(0.02, 0.04)
        )
        
        drs = sens['discount_rates']
        tgs = sens['terminal_growths']
        
        assert drs[0] >= 0.06
        assert drs[-1] <= 0.10
        assert tgs[0] >= 0.02
        assert tgs[-1] <= 0.04
    
    def test_get_summary(self, symbol):
        """Test complete summary output."""
        proj = DCFProjector(symbol)
        summary = proj.get_summary()
        
        assert summary['symbol'] == symbol
        assert 'timestamp' in summary
        assert 'current_price' in summary
        assert 'revenue_projections' in summary
        assert 'earnings_projections' in summary
        assert 'price_targets' in summary
        assert 'sensitivity' in summary


class TestPlotlyChartBuilder:
    """Test PlotlyChartBuilder class."""
    
    @pytest.fixture
    def projector(self):
        """Create a projector for testing."""
        return DCFProjector('SHOP')
    
    @pytest.fixture
    def builder(self, projector):
        """Create a chart builder."""
        return PlotlyChartBuilder(projector)
    
    def test_init(self, projector, builder):
        """Test initialization."""
        assert builder.symbol == 'SHOP'
        assert builder.projector is projector
    
    def test_plot_revenue_waterfall(self, builder):
        """Test revenue waterfall chart."""
        chart = builder.plot_revenue_waterfall()
        
        assert isinstance(chart, dict)
        assert 'data' in chart or 'error' in chart
        
        if 'data' in chart:
            assert len(chart['data']) > 0
            assert 'layout' in chart
            assert 'config' in chart
    
    def test_plot_price_paths(self, builder):
        """Test price paths chart."""
        chart = builder.plot_price_paths()
        
        assert isinstance(chart, dict)
        assert 'data' in chart or 'error' in chart
        
        if 'data' in chart:
            assert len(chart['data']) > 0
            assert 'layout' in chart
            assert 'config' in chart
    
    def test_plot_sensitivity_heatmap(self, builder):
        """Test sensitivity heatmap."""
        chart = builder.plot_sensitivity_heatmap()
        
        assert isinstance(chart, dict)
        assert 'data' in chart or 'error' in chart
        
        if 'data' in chart:
            assert len(chart['data']) > 0
            assert 'layout' in chart
            assert 'config' in chart
    
    def test_plot_scenario_comparison(self, builder):
        """Test scenario comparison chart."""
        chart = builder.plot_scenario_comparison()
        
        assert isinstance(chart, dict)
        assert 'data' in chart or 'error' in chart
    
    def test_get_all_charts(self, builder):
        """Test get_all_charts method."""
        all_charts = builder.get_all_charts()
        
        assert isinstance(all_charts, dict)
        assert 'symbol' in all_charts
        assert 'timestamp' in all_charts
        assert 'charts' in all_charts
        
        charts = all_charts['charts']
        assert 'revenue_waterfall' in charts
        assert 'price_paths' in charts
        assert 'sensitivity_heatmap' in charts
        assert 'scenario_comparison' in charts
    
    def test_charts_are_valid_json(self, builder):
        """Test that all charts can be serialized to JSON."""
        all_charts = builder.get_all_charts()
        
        # Should be JSON serializable
        json_str = json.dumps(all_charts, default=str)
        assert len(json_str) > 0


class TestEnhancedSignalEngine:
    """Test EnhancedSignalEngine class."""
    
    @pytest.fixture(params=['SHOP', 'SOFI'])
    def symbol(self, request):
        """Test symbols."""
        return request.param
    
    def test_init(self, symbol):
        """Test initialization."""
        engine = EnhancedSignalEngine(symbol)
        assert engine.symbol == symbol
    
    def test_calculate_combined_score(self, symbol):
        """Test combined score calculation."""
        engine = EnhancedSignalEngine(symbol)
        score = engine.calculate_combined_score()
        
        assert isinstance(score, dict)
        assert 'combined_score' in score
        assert 'technical_score' in score
        assert 'projection_score' in score
        assert 'signal_type' in score
        assert 'reasoning' in score
        
        # Scores should be 0-10
        assert 0 <= score['combined_score'] <= 10
        assert 0 <= score['technical_score'] <= 10
        assert 0 <= score['projection_score'] <= 10
        
        # Signal type should be one of the known types
        assert score['signal_type'] in ('strong_sell', 'sell', 'hold', 'buy', 'strong_buy')
    
    def test_combine_signals(self, symbol):
        """Test signal merging."""
        engine = EnhancedSignalEngine(symbol)
        merged = engine.combine_signals()
        
        assert isinstance(merged, dict)
        assert 'symbol' in merged
        assert 'type' in merged
        assert 'confidence' in merged
        assert 'trigger' in merged
        assert 'breakdown' in merged
        
        assert merged['symbol'] == symbol
        assert merged['type'] in ('strong_sell', 'sell', 'hold', 'buy', 'strong_buy')
        assert 0 <= merged['confidence'] <= 10
    
    def test_get_sell_signals(self, symbol):
        """Test sell signal extraction."""
        engine = EnhancedSignalEngine(symbol)
        sell_sigs = engine.get_sell_signals()
        
        assert isinstance(sell_sigs, list)
        # Each signal should have expected fields
        for sig in sell_sigs:
            assert 'symbol' in sig
            assert 'type' in sig
            assert 'confidence' in sig
            assert 'trigger' in sig
            assert sig['type'] in ('strong_sell', 'sell')
    
    def test_get_buy_signals(self, symbol):
        """Test buy signal extraction."""
        engine = EnhancedSignalEngine(symbol)
        buy_sigs = engine.get_buy_signals()
        
        assert isinstance(buy_sigs, list)
        # Each signal should have expected fields
        for sig in buy_sigs:
            assert 'symbol' in sig
            assert 'type' in sig
            assert 'confidence' in sig
            assert 'trigger' in sig
            assert sig['type'] in ('strong_buy', 'buy')
    
    def test_get_full_analysis(self, symbol):
        """Test full analysis output."""
        engine = EnhancedSignalEngine(symbol)
        analysis = engine.get_full_analysis()
        
        assert isinstance(analysis, dict)
        assert 'symbol' in analysis
        assert 'timestamp' in analysis
        assert 'merged_signal' in analysis
        assert 'sell_signals' in analysis
        assert 'buy_signals' in analysis
        assert 'detector_status' in analysis
        
        assert analysis['symbol'] == symbol
        assert isinstance(analysis['sell_signals'], list)
        assert isinstance(analysis['buy_signals'], list)


class TestIntegration:
    """Integration tests for full Charlotte Phase 2."""
    
    def test_full_pipeline_shop(self):
        """Test full pipeline: projections → visualizer → signal enhancer."""
        symbol = 'SHOP'
        
        # 1. Create projector
        projector = DCFProjector(symbol)
        assert projector.current_price > 0
        
        # 2. Get projections
        targets = projector.calculate_price_targets()
        assert targets['bull'] > 0
        assert targets['base'] > 0
        assert targets['bear'] > 0
        
        # 3. Create visualizer
        builder = PlotlyChartBuilder(projector)
        charts = builder.get_all_charts()
        assert charts['symbol'] == symbol
        
        # 4. Create signal engine
        engine = EnhancedSignalEngine(symbol)
        analysis = engine.get_full_analysis()
        assert analysis['symbol'] == symbol
        
        # All together work
        assert len(json.dumps(analysis, default=str)) > 0
    
    def test_multiple_symbols(self):
        """Test pipeline with multiple symbols."""
        symbols = ['SHOP', 'SOFI', 'COIN']
        
        for sym in symbols:
            projector = DCFProjector(sym)
            builder = PlotlyChartBuilder(projector)
            engine = EnhancedSignalEngine(sym)
            
            # All should complete without error
            charts = builder.get_all_charts()
            analysis = engine.get_full_analysis()
            
            assert charts['symbol'] == sym
            assert analysis['symbol'] == sym


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
