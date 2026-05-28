#!/usr/bin/env python3
"""Charlotte Crew: Multi-agent orchestration for Phase 2 (Projections, Visualizer, Signals).

Uses LangChain with Anthropic Opus (architecture) and Haiku (data validation).
No local Ollama — pure cloud models only.

Public API:
    run_projection_task(symbol) → projections dict
    run_visualizer_task(symbol) → charts dict
    run_signal_task(symbol) → merged signal dict
    run_full_charlotte(symbol) → complete analysis
"""
import sys
import json
from datetime import datetime
from typing import Dict, Optional, List

# Add hermes to path
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

try:
    from charlotte.projections import DCFProjector
    from charlotte.visualizer import PlotlyChartBuilder
    from charlotte.signal_enhancer import EnhancedSignalEngine
except ImportError:
    from projections import DCFProjector
    from visualizer import PlotlyChartBuilder
    from signal_enhancer import EnhancedSignalEngine
from charlotte.signal_engine_v2 import get_enhanced_signal, get_enhanced_analysis


class ProjectionTask:
    """Task: Generate DCF projections for a symbol."""
    
    @staticmethod
    def execute(symbol: str) -> Dict:
        """Run projection task.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Dict with projections, price targets, and sensitivity analysis.
        """
        try:
            projector = DCFProjector(symbol, quarters_ahead=12)
            summary = projector.get_summary()
            
            return {
                'task': 'projection',
                'symbol': symbol,
                'status': 'success',
                'output': summary,
                'timestamp': datetime.now().isoformat(),
            }
        except (ValueError, KeyError, AttributeError, ConnectionError) as e:
            return {
                'task': 'projection',
                'symbol': symbol,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            }


class VisualizerTask:
    """Task: Generate Plotly charts for projections."""
    
    @staticmethod
    def execute(symbol: str) -> Dict:
        """Run visualizer task.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Dict with all Plotly JSON charts.
        """
        try:
            projector = DCFProjector(symbol)
            builder = PlotlyChartBuilder(projector)
            charts = builder.get_all_charts()
            
            return {
                'task': 'visualizer',
                'symbol': symbol,
                'status': 'success',
                'output': charts,
                'timestamp': datetime.now().isoformat(),
            }
        except (ValueError, KeyError, AttributeError, ConnectionError) as e:
            return {
                'task': 'visualizer',
                'symbol': symbol,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            }


class SignalTask:
    """Task: Merge technical signals with DCF projections."""
    
    @staticmethod
    def execute(symbol: str) -> Dict:
        """Run signal merging task.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Dict with merged signal, buy/sell recommendations.
        """
        try:
            analysis = get_enhanced_analysis(symbol)
            
            return {
                'task': 'signal',
                'symbol': symbol,
                'status': 'success',
                'output': analysis,
                'timestamp': datetime.now().isoformat(),
            }
        except (ValueError, KeyError, AttributeError, ConnectionError) as e:
            return {
                'task': 'signal',
                'symbol': symbol,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
            }


class CharlotteCrew:
    """Orchestrate all Phase 2 tasks."""
    
    def __init__(self):
        """Initialize crew."""
        self.projection_task = ProjectionTask()
        self.visualizer_task = VisualizerTask()
        self.signal_task = SignalTask()
    
    def run_full_charlotte(self, symbol: str) -> Dict:
        """Execute all three tasks for complete analysis.
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Dict with projections, charts, and signals.
        """
        symbol = symbol.upper()
        
        results = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'tasks': [],
        }
        
        # Run projection task
        proj_result = self.projection_task.execute(symbol)
        results['tasks'].append(proj_result)
        
        # Run visualizer task
        viz_result = self.visualizer_task.execute(symbol)
        results['tasks'].append(viz_result)
        
        # Run signal task
        sig_result = self.signal_task.execute(symbol)
        results['tasks'].append(sig_result)
        
        # Aggregate results
        results['projections'] = proj_result['output'] if proj_result['status'] == 'success' else None
        results['charts'] = viz_result['output'] if viz_result['status'] == 'success' else None
        results['signal'] = sig_result['output'] if sig_result['status'] == 'success' else None
        
        results['overall_status'] = 'success' if all(t['status'] == 'success' for t in results['tasks']) else 'partial'
        
        return results
    
    def run_batch(self, symbols: List[str]) -> Dict:
        """Execute full Charlotte for multiple symbols.
        
        Args:
            symbols: List of stock tickers
        
        Returns:
            Dict with results for all symbols.
        """
        results = {
            'symbols': symbols,
            'timestamp': datetime.now().isoformat(),
            'analyses': [],
        }
        
        for symbol in symbols:
            try:
                analysis = self.run_full_charlotte(symbol)
                results['analyses'].append(analysis)
            except (ValueError, KeyError, AttributeError, ConnectionError) as e:
                results['analyses'].append({
                    'symbol': symbol,
                    'status': 'error',
                    'error': str(e),
                })
        
        results['success_count'] = sum(1 for a in results['analyses'] if a.get('overall_status') == 'success')
        results['failure_count'] = len(symbols) - results['success_count']
        
        return results


# Module-level convenience functions

def run_projection_task(symbol: str) -> Dict:
    """Execute projection task for a symbol.
    
    Args:
        symbol: Stock ticker
    
    Returns:
        Projections dict
    """
    return ProjectionTask.execute(symbol)


def run_visualizer_task(symbol: str) -> Dict:
    """Execute visualizer task for a symbol.
    
    Args:
        symbol: Stock ticker
    
    Returns:
        Charts dict
    """
    return VisualizerTask.execute(symbol)


def run_signal_task(symbol: str) -> Dict:
    """Execute signal task for a symbol.
    
    Args:
        symbol: Stock ticker
    
    Returns:
        Signal analysis dict
    """
    return SignalTask.execute(symbol)


def run_full_charlotte(symbol: str) -> Dict:
    """Execute full Charlotte Phase 2 for a symbol.
    
    Args:
        symbol: Stock ticker
    
    Returns:
        Complete analysis dict
    """
    crew = CharlotteCrew()
    return crew.run_full_charlotte(symbol)


def run_batch_charlotte(symbols: List[str]) -> Dict:
    """Execute full Charlotte Phase 2 for multiple symbols.
    
    Args:
        symbols: List of stock tickers
    
    Returns:
        Batch analysis dict
    """
    crew = CharlotteCrew()
    return crew.run_batch(symbols)


if __name__ == '__main__':
    import argparse
    
    p = argparse.ArgumentParser(description='Charlotte Crew: Phase 2 Orchestration')
    p.add_argument('symbols', nargs='+', help='Stock symbols')
    p.add_argument('--task', choices=['projection', 'visualizer', 'signal', 'full'], 
                   default='full', help='Task to run (default: full)')
    p.add_argument('--output', help='Output file path (default: stdout)')
    
    args = p.parse_args()
    
    # Run single or batch
    if len(args.symbols) == 1:
        symbol = args.symbols[0]
        if args.task == 'projection':
            result = run_projection_task(symbol)
        elif args.task == 'visualizer':
            result = run_visualizer_task(symbol)
        elif args.task == 'signal':
            result = run_signal_task(symbol)
        else:  # full
            result = run_full_charlotte(symbol)
    else:
        if args.task == 'full':
            result = run_batch_charlotte(args.symbols)
        else:
            result = {
                'error': 'Batch mode only supports --task full',
                'symbols': args.symbols,
            }
    
    # Output
    output_json = json.dumps(result, indent=2, default=str)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Results written to {args.output}")
    else:
        print(output_json)
