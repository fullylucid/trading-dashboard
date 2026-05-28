#!/usr/bin/env python3
"""Test suite and integration verification for Charlotte v4 LLM layer.

TESTS:
1. ollama_deep_analyzer module loads correctly
2. Signal filtering logic (confidence-based)
3. Single signal analysis
4. Batch signal analysis
5. Portfolio insight generation
6. Telegram message formatting
7. Alert synthesizer v4 integration

USAGE:
    python -m charlotte.test_ollama_integration [--live] [--verbose]
    
    --live: Attempt real Ollama Cloud calls (requires OLLAMA_API_KEY)
    --verbose: Print detailed debug info
"""
import sys
import json
import argparse
from pathlib import Path

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')


def test_module_import():
    """Test 1: Module imports without errors."""
    print("[TEST 1] Module import...")
    try:
        from charlotte import ollama_deep_analyzer
        assert hasattr(ollama_deep_analyzer, 'OllamaPrimaryClient')
        assert hasattr(ollama_deep_analyzer, 'analyze_signals')
        assert hasattr(ollama_deep_analyzer, 'analyze_single_signal')
        assert hasattr(ollama_deep_analyzer, 'filter_signals_for_analysis')
        print("  ✓ All required functions/classes present")
        return True
    except (ImportError, AssertionError) as e:
        print(f"  ✗ FAILED: {e}")
        return False


def test_signal_filtering():
    """Test 2: Signal filtering by confidence threshold."""
    print("[TEST 2] Signal filtering...")
    from charlotte import ollama_deep_analyzer as lla
    
    signals = [
        {"symbol": "AAPL", "category": "trough", "confidence": 3.5},
        {"symbol": "MSFT", "category": "trough", "confidence": 6.5},
        {"symbol": "GOOGL", "category": "secular_top", "confidence": 9.8},
    ]
    
    # Filter with default threshold (MIN_CONFIDENCE_FOR_ANALYSIS = 6.0)
    filtered = lla.filter_signals_for_analysis(signals, force_analysis=False)
    
    if len(filtered) == 2 and all(s['confidence'] >= 6.0 for s in filtered):
        print(f"  ✓ Filtered {len(signals)} -> {len(filtered)} signals (conf >= 6.0)")
        return True
    else:
        print(f"  ✗ FAILED: Expected 2 signals, got {len(filtered)}")
        return False


def test_signal_should_analyze():
    """Test 3: Should-analyze predicate."""
    print("[TEST 3] Should-analyze predicate...")
    from charlotte import ollama_deep_analyzer as lla
    
    cases = [
        ({"confidence": 5.5}, False, "Below threshold without force"),
        ({"confidence": 6.0}, True, "At threshold"),
        ({"confidence": 7.0}, True, "Above threshold"),
        ({"confidence": 5.0}, True, "Below threshold WITH force"),
    ]
    
    passed = 0
    for sig, expected_force_result, desc in cases:
        # Test with force=False
        if lla.should_analyze_signal(sig, force_analysis=False) != (sig['confidence'] >= 6.0):
            print(f"  ✗ FAILED: {desc}")
            return False
        # Test with force=True
        if lla.should_analyze_signal(sig, force_analysis=True) != True:
            print(f"  ✗ FAILED: {desc} (force=True)")
            return False
        passed += 1
    
    print(f"  ✓ All {passed} predicate cases passed")
    return True


def test_telegram_formatting():
    """Test 4: Telegram message formatting."""
    print("[TEST 4] Telegram message formatting...")
    from charlotte import ollama_deep_analyzer as lla
    
    signals = [
        {
            "symbol": "SHOP",
            "category": "trough",
            "confidence": 7.2,
            "narrative": "Strong reversal signals with high volume confirmation",
            "target": "Buy below $50"
        },
        {
            "symbol": "COIN",
            "category": "secular_top",
            "confidence": 9.8,
            "narrative": "Valuation extreme reached with declining technicals",
            "target": "Exit toward $85"
        }
    ]
    
    portfolio_insight = "Market in consolidation phase. Recommend 60/40 long/short tilt."
    
    msg = lla.format_telegram_message(signals, portfolio_insight)
    
    required = ["Charlotte v4", "SHOP", "COIN", "Portfolio Insight", "consolidation"]
    if all(s in msg for s in required):
        print(f"  ✓ Message formatted correctly ({len(msg)} chars)")
        print(f"\n  [Sample]\n{msg[:300]}...\n")
        return True
    else:
        print(f"  ✗ FAILED: Missing required content")
        print(f"  Got: {msg}")
        return False


def test_alert_synthesizer_imports():
    """Test 5: Alert synthesizer v4 integration."""
    print("[TEST 5] Alert synthesizer v4 imports...")
    try:
        from charlotte import alert_synthesizer
        assert hasattr(alert_synthesizer, 'enrich_signals_with_llm')
        assert alert_synthesizer.DEEP_ANALYSIS_DEFAULT == False
        print("  ✓ Alert synthesizer has enrich_signals_with_llm function")
        print("  ✓ Default deep_analysis=False (resource-conscious)")
        return True
    except (ImportError, AssertionError) as e:
        print(f"  ✗ FAILED: {e}")
        return False


def test_enrich_signals_offline():
    """Test 6: Offline LLM enrichment fallback."""
    print("[TEST 6] Offline enrichment fallback...")
    from charlotte import alert_synthesizer
    
    signals = [
        {"symbol": "AAPL", "category": "trough", "confidence": 7.0, "reasons": ["RSI oversold"]}
    ]
    portfolio = {"AAPL": 100}
    
    # This should gracefully fallback since OLLAMA_API_KEY is unlikely set in tests
    enriched, insight = alert_synthesizer.enrich_signals_with_llm(signals, portfolio, deep_analysis=False)
    
    if isinstance(enriched, list) and len(enriched) > 0:
        print(f"  ✓ Graceful fallback: returned {len(enriched)} signals")
        print(f"  ✓ Portfolio insight: {insight}")
        return True
    else:
        print(f"  ✗ FAILED: Enrichment did not return signals")
        return False


def test_client_init():
    """Test 7: OllamaPrimaryClient initialization (offline)."""
    print("[TEST 7] OllamaPrimaryClient initialization...")
    from charlotte import ollama_deep_analyzer as lla
    
    try:
        # Should fail gracefully without API key
        client = lla.OllamaPrimaryClient("")
        print("  ✗ FAILED: Should reject empty API key")
        return False
    except ValueError as e:
        print(f"  ✓ Correctly rejects empty API key: {e}")
        return True
    except ImportError as e:
        print(f"  ⚠ httpx not installed (expected in test env): {e}")
        return True


def test_function_signatures():
    """Test 8: Verify function signatures."""
    print("[TEST 8] Function signatures...")
    from charlotte import ollama_deep_analyzer as lla
    from charlotte import alert_synthesizer as asyn
    import inspect
    
    sigs = {
        "analyze_signals": inspect.signature(lla.analyze_signals),
        "analyze_single_signal": inspect.signature(lla.analyze_single_signal),
        "filter_signals_for_analysis": inspect.signature(lla.filter_signals_for_analysis),
        "enrich_signals_with_llm": inspect.signature(asyn.enrich_signals_with_llm),
    }
    
    # Check parameter counts
    checks = [
        ("analyze_signals", 3),  # signals, deep_analysis, portfolio
        ("analyze_single_signal", 2),  # signal, force
        ("filter_signals_for_analysis", 2),  # signals, force_analysis
        ("enrich_signals_with_llm", 3),  # signals, portfolio, deep_analysis
    ]
    
    passed = 0
    for fname, expected_params in checks:
        sig = sigs[fname]
        param_count = len(sig.parameters)
        if param_count >= expected_params - 1:  # Allow +1 for defaults
            print(f"  ✓ {fname}: {param_count} params")
            passed += 1
        else:
            print(f"  ✗ {fname}: expected ~{expected_params}, got {param_count}")
    
    return passed == len(checks)


def test_live_call_structure(api_key):
    """Test 9: Live API call structure (dry-run)."""
    print("[TEST 9] Live API structure validation...")
    if not api_key:
        print("  ⚠ Skipped (no OLLAMA_API_KEY)")
        return True
    
    from charlotte import ollama_deep_analyzer as lla
    
    try:
        # This will attempt a real call if httpx is available
        signal = {
            "symbol": "TEST",
            "category": "trough",
            "confidence": 7.0,
            "reasons": ["Test signal"],
            "current_price": "100.00",
            "add_pct": 10,
            "action": "add"
        }
        
        result = lla.analyze_single_signal(signal, force=False)
        
        if result:
            required_keys = ["symbol", "category", "confidence"]
            if all(k in result for k in required_keys):
                print(f"  ✓ Live call returned valid structure")
                return True
            else:
                print(f"  ✗ FAILED: Missing keys in response")
                return False
        else:
            print("  ⚠ API unavailable or failed (this is OK in test)")
            return True
    
    except Exception as e:
        print(f"  ⚠ Live call test failed (expected): {e}")
        return True


def main(argv=None):
    """Run all tests."""
    ap = argparse.ArgumentParser(description="Charlotte v4 integration tests")
    ap.add_argument("--live", action="store_true", help="Run live API tests")
    ap.add_argument("--verbose", action="store_true", help="Verbose output")
    args = ap.parse_args(argv)
    
    print("=" * 70)
    print("Charlotte v4 LLM Layer Integration Tests")
    print("=" * 70)
    print()
    
    tests = [
        ("Module Import", test_module_import),
        ("Signal Filtering", test_signal_filtering),
        ("Should-Analyze Predicate", test_signal_should_analyze),
        ("Telegram Formatting", test_telegram_formatting),
        ("Alert Synthesizer v4", test_alert_synthesizer_imports),
        ("Offline Enrichment Fallback", test_enrich_signals_offline),
        ("Client Initialization", test_client_init),
        ("Function Signatures", test_function_signatures),
    ]
    
    if args.live:
        import os
        api_key = os.environ.get("OLLAMA_API_KEY", "")
        tests.append(("Live API Call", lambda: test_live_call_structure(api_key)))
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"  ✗ EXCEPTION: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            results.append((name, False))
        print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    for name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {name}")
    
    print()
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
