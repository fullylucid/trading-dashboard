#!/usr/bin/env python3
"""Signal Engine v2: Extended API with enhanced signal merging.

Extends Charlotte signal handling with DCF projections integration.

Public API:
    get_enhanced_signal(symbol) → merged signal dict with confidence, target, trigger
"""
import sys
import json
from typing import Optional, Dict, List

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

try:
    from hermes.charlotte.signal_enhancer import EnhancedSignalEngine
except ImportError:
    try:
        from charlotte.signal_enhancer import EnhancedSignalEngine
    except ImportError:
        from signal_enhancer import EnhancedSignalEngine


def get_enhanced_signal(symbol: str) -> Dict:
    """Get enhanced signal merging technical + DCF projection.
    
    Args:
        symbol: Stock ticker
    
    Returns:
        Dict with keys:
            symbol: Stock ticker
            type: Signal type (strong_sell, sell, hold, buy, strong_buy)
            confidence: Confidence (0-10)
            trigger: Reason
            target: Price target
            breakdown: Technical and projection details
            timestamp: ISO timestamp
    
    Example:
        >>> sig = get_enhanced_signal('SHOP')
        >>> print(sig['type'], sig['confidence'], sig['target'])
        strong_sell 8.2 145.8
    """
    try:
        engine = EnhancedSignalEngine(symbol)
        return engine.combine_signals()
    except (ValueError, KeyError, AttributeError, ConnectionError) as e:
        return {
            'symbol': symbol.upper(),
            'type': 'error',
            'confidence': 0,
            'trigger': str(e),
            'target': None,
            'error': str(e),
        }


def get_enhanced_analysis(symbol: str) -> Dict:
    """Get complete enhanced analysis with sell and buy signals.
    
    Args:
        symbol: Stock ticker
    
    Returns:
        Dict with full analysis including merged signal, buy/sell signals, and detector status.
    """
    try:
        engine = EnhancedSignalEngine(symbol)
        return engine.get_full_analysis()
    except (ValueError, KeyError, AttributeError, ConnectionError) as e:
        return {
            'symbol': symbol.upper(),
            'error': str(e),
        }


def batch_enhanced_signals(symbols: List[str]) -> List[Dict]:
    """Get enhanced signals for multiple symbols.
    
    Args:
        symbols: List of stock tickers
    
    Returns:
        List of signal dicts, sorted by confidence descending.
    """
    signals = []
    for sym in symbols:
        try:
            sig = get_enhanced_signal(sym)
            if sig and 'error' not in sig:
                signals.append(sig)
        except (ValueError, KeyError, AttributeError, ConnectionError):
            continue
    
    return sorted(signals, key=lambda x: -x.get('confidence', 0))


def get_sell_recommendations(symbols: List[str], min_confidence: float = 7.0) -> List[Dict]:
    """Get sell signals (strong_sell, sell) above confidence threshold.
    
    Args:
        symbols: List of stock tickers
        min_confidence: Minimum confidence (0-10)
    
    Returns:
        List of sell signals, sorted by confidence descending.
    """
    sell_sigs = []
    for sym in symbols:
        try:
            analysis = get_enhanced_analysis(sym)
            if 'error' not in analysis:
                sigs = analysis.get('sell_signals', [])
                for sig in sigs:
                    if sig.get('confidence', 0) >= min_confidence:
                        sell_sigs.append(sig)
        except (ValueError, KeyError, AttributeError, ConnectionError):
            continue
    
    return sorted(sell_sigs, key=lambda x: -x.get('confidence', 0))


def get_buy_recommendations(symbols: List[str], min_confidence: float = 7.0) -> List[Dict]:
    """Get buy signals (strong_buy, buy) above confidence threshold.
    
    Args:
        symbols: List of stock tickers
        min_confidence: Minimum confidence (0-10)
    
    Returns:
        List of buy signals, sorted by confidence descending.
    """
    buy_sigs = []
    for sym in symbols:
        try:
            analysis = get_enhanced_analysis(sym)
            if 'error' not in analysis:
                sigs = analysis.get('buy_signals', [])
                for sig in sigs:
                    if sig.get('confidence', 0) >= min_confidence:
                        buy_sigs.append(sig)
        except (ValueError, KeyError, AttributeError, ConnectionError):
            continue
    
    return sorted(buy_sigs, key=lambda x: -x.get('confidence', 0))


if __name__ == '__main__':
    import argparse
    
    p = argparse.ArgumentParser(description='Charlotte Enhanced Signal Engine v2')
    p.add_argument('--symbol', nargs='+', required=True, help='Stock symbols')
    p.add_argument('--analysis', action='store_true', help='Get full analysis (not just merged signal)')
    p.add_argument('--sell', action='store_true', help='Get sell signals')
    p.add_argument('--buy', action='store_true', help='Get buy signals')
    p.add_argument('--min-conf', type=float, default=7.0, help='Minimum confidence threshold')
    
    args = p.parse_args()
    
    if args.sell:
        results = get_sell_recommendations(args.symbol, min_confidence=args.min_conf)
    elif args.buy:
        results = get_buy_recommendations(args.symbol, min_confidence=args.min_conf)
    elif args.analysis:
        results = [get_enhanced_analysis(sym) for sym in args.symbol]
    else:
        results = batch_enhanced_signals(args.symbol)
    
    print(json.dumps(results, indent=2, default=str))
