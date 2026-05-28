#!/usr/bin/env python3
"""Charlotte v4 LLM Layer - Ollama Cloud Deep Analyzer.

Generates narrative explanations for troughs, secular tops, and portfolio insights
using sequential model calling (primary: kimi-k2.6:cloud, secondary: qwen3-coder:480b-cloud).

Activates only on LIVE SIGNALS or explicit --deep-analysis flag.
Never runs during backtests. Core Python detectors/scorer/regime gate untouched.

USAGE:
    python -m charlotte.ollama_deep_analyzer --signal <json-signal>
    python -m charlotte.ollama_deep_analyzer --signals <json-array> [--deep-analysis]
    python -m charlotte.ollama_deep_analyzer --trough SHOP 3.1
    python -m charlotte.ollama_deep_analyzer --secular-top COIN 9.8

ENV:
    OLLAMA_API_KEY: Ollama Cloud API key (required for cloud models)
    OLLAMA_BASE_URL: Optional; defaults to https://api.ollama.cloud/v1
"""
import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import logging

try:
    import httpx
except ImportError:
    httpx = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("ollama_deep_analyzer")


# ============================ CONFIG ============================ #

OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://api.ollama.cloud/v1")

# Model endpoints
PRIMARY_MODEL = "kimi-k2.6:cloud"      # All tasks
SECONDARY_MODEL = "qwen3-coder:480b-cloud"  # Code/technical only

# Rate limit / concurrency: max 2 models active at once (Ollama Cloud Pro = 3 concurrent, reserve 1)
MAX_CONCURRENT = 2

# Request timeout
TIMEOUT_SECONDS = 120

# Min confidence to trigger deep analysis (if --deep-analysis flag set)
MIN_CONFIDENCE_FOR_ANALYSIS = 6.0


# ============================ OLLAMA CLIENT ============================ #

class OllamaPrimaryClient:
    """Sequential model caller using Ollama Cloud API via httpx.
    
    Signature:
        __init__(api_key: str, base_url: str) -> None
        call_model(model: str, prompt: str, timeout: int) -> Optional[str]
        analyze_signal(signal: dict) -> Optional[dict]
        analyze_batch(signals: list[dict]) -> list[dict]
    """
    
    def __init__(self, api_key: str, base_url: str = OLLAMA_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Initialize httpx client with auth headers."""
        if not httpx:
            raise ImportError("httpx required for Ollama Cloud. Install: pip install httpx")
        if not self.api_key:
            raise ValueError("OLLAMA_API_KEY environment variable not set")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.Client(headers=headers, timeout=TIMEOUT_SECONDS)
    
    def call_model(self, model: str, prompt: str, timeout: int = TIMEOUT_SECONDS) -> Optional[str]:
        """Call a single model endpoint.
        
        Args:
            model: Model identifier (e.g., 'kimi-k2.6:cloud')
            prompt: Input prompt/message
            timeout: Request timeout in seconds
            
        Returns:
            Model response text, or None on error
        """
        if not self.client:
            return None
        
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        
        try:
            logger.info(f"Calling {model}...")
            response = self.client.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info(f"{model} returned {len(text)} chars")
            return text
        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.error(f"{model} error: {e}")
            return None
    
    def analyze_signal(self, signal: dict) -> Optional[dict]:
        """Deep analyze a single signal with primary model.
        
        Args:
            signal: Signal dict from detector (must have 'symbol', 'category', 'confidence', 'reasons')
            
        Returns:
            Dict with keys: symbol, category, narrative, action_plan, risks
            Or None if analysis failed
        """
        symbol = signal.get("symbol", "UNKNOWN")
        category = signal.get("category", "unknown")
        reasons = signal.get("reasons", [])
        confidence = signal.get("confidence", 0.0)
        current_price = signal.get("current_price", "N/A")
        
        # Build prompt for primary model
        if category == "trough":
            action = signal.get("action", "add")
            add_pct = signal.get("add_pct", 10)
            prompt = f"""Analyze this TROUGH (buy opportunity) signal for {symbol}:

Symbol: {symbol}
Current Price: ${current_price}
Confidence: {confidence:.1f}/10
Signals: {', '.join(reasons)}
Action: {action.upper()} {add_pct}% to core position

Generate a concise narrative (2-3 sentences) explaining why this is a good entry point.
Also provide: 1) Main risk to monitor, 2) Price target if trade works.
Format: NARRATIVE | RISK | TARGET"""
        
        elif category == "secular_top":
            trim_pct = signal.get("trim_pct", 50)
            prompt = f"""Analyze this SECULAR TOP (sell signal) for {symbol}:

Symbol: {symbol}
Current Price: ${current_price}
Confidence: {confidence:.1f}/10
Signals: {', '.join(reasons)}
Action: TRIM {trim_pct}%

Generate a concise narrative (2-3 sentences) on why fundamentals/technicals suggest peak.
Also provide: 1) Level to watch if reversal happens, 2) Downside target.
Format: NARRATIVE | REVERSAL_LEVEL | TARGET"""
        
        elif category == "momentum_trim":
            trim_pct = signal.get("trim_pct", 30)
            trail_pct = signal.get("trail_pct", 10)
            prompt = f"""Analyze this MOMENTUM PEAK (trim signal) for {symbol}:

Symbol: {symbol}
Current Price: ${current_price}
Confidence: {confidence:.1f}/10
Signals: {', '.join(reasons)}
Action: TRIM {trim_pct}%, trail core at {trail_pct}%

Generate a concise narrative (2-3 sentences) on overbought conditions and momentum exhaustion.
Also provide: 1) Retracement level to watch, 2) Scale-back strategy.
Format: NARRATIVE | RETRACEMENT | STRATEGY"""
        
        else:
            prompt = f"Analyze signal for {symbol} ({category}): {', '.join(reasons)}"
        
        narrative = self.call_model(PRIMARY_MODEL, prompt)
        if not narrative:
            return None
        
        # Parse output
        parts = narrative.split("|")
        return {
            "symbol": symbol,
            "category": category,
            "confidence": confidence,
            "narrative": parts[0].strip() if len(parts) > 0 else narrative,
            "secondary_insight": parts[1].strip() if len(parts) > 1 else "",
            "target": parts[2].strip() if len(parts) > 2 else "",
            "timestamp": datetime.now().isoformat(),
        }
    
    def analyze_batch(self, signals: list[dict]) -> list[dict]:
        """Analyze multiple signals sequentially.
        
        Args:
            signals: List of signal dicts
            
        Returns:
            List of analyzed dicts (same length; None entries for failures)
        """
        results = []
        for i, sig in enumerate(signals):
            logger.info(f"Analyzing signal {i+1}/{len(signals)}: {sig.get('symbol')}")
            result = self.analyze_signal(sig)
            results.append(result if result else {
                "symbol": sig.get("symbol", "UNKNOWN"),
                "category": sig.get("category", "unknown"),
                "confidence": sig.get("confidence", 0.0),
                "narrative": "Analysis unavailable",
                "timestamp": datetime.now().isoformat(),
            })
        return results
    
    def portfolio_insight(self, signals: list[dict], portfolio: Dict[str, float]) -> Optional[str]:
        """Generate portfolio-level insight from all signals.
        
        Args:
            signals: List of analyzed signal dicts
            portfolio: Dict of {symbol: quantity}
            
        Returns:
            Narrative text with portfolio recommendations, or None
        """
        if not signals:
            return None
        
        troughs = [s for s in signals if s.get("category") == "trough"]
        tops = [s for s in signals if s.get("category") == "secular_top"]
        trims = [s for s in signals if s.get("category") == "momentum_trim"]
        
        top_symbols = sorted(signals, key=lambda x: -x.get("confidence", 0))[:5]
        top_list = ", ".join([f"{s.get('symbol')} ({s.get('category')}, {s.get('confidence', 0):.1f})" 
                              for s in top_symbols])
        
        prompt = f"""Portfolio alert summary:
Troughs (buys): {len(troughs)} signals
Secular Tops (thesis reviews): {len(tops)} signals
Momentum Trims: {len(trims)} signals

Top opportunities: {top_list}

Provide a brief (3-4 sentence) portfolio-level recommendation:
1) Current market regime/bias
2) Recommended portfolio rebalance approach
3) Key watch items for next 24h

Keep it actionable and concise."""
        
        insight = self.call_model(PRIMARY_MODEL, prompt)
        return insight if insight else None
    
    def close(self):
        """Close client connection."""
        if self.client:
            self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


# ============================ SIGNAL FILTERING ============================ #

def should_analyze_signal(signal: dict, force_analysis: bool = False) -> bool:
    """Determine if signal warrants deep LLM analysis.
    
    Args:
        signal: Signal dict with 'confidence' key
        force_analysis: If True, analyze all non-None signals
        
    Returns:
        True if analysis should run
    """
    if force_analysis:
        return True
    
    conf = signal.get("confidence", 0.0)
    return conf >= MIN_CONFIDENCE_FOR_ANALYSIS


def filter_signals_for_analysis(signals: list[dict], force_analysis: bool = False) -> list[dict]:
    """Filter signals that should be analyzed.
    
    Args:
        signals: Raw signal list
        force_analysis: If True, analyze all
        
    Returns:
        Filtered list
    """
    return [s for s in signals if should_analyze_signal(s, force_analysis)]


# ============================ FORMAT OUTPUT ============================ #

def format_telegram_message(analyzed_signals: list[dict], portfolio_insight: Optional[str] = None) -> str:
    """Format analyzed signals into Telegram-ready message.
    
    Args:
        analyzed_signals: List of analyzed signal dicts
        portfolio_insight: Optional portfolio-level narrative
        
    Returns:
        Formatted message string
    """
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    lines.append(f"🕷️ Charlotte v4 Deep Analysis — {now}")
    lines.append("")
    
    # Group by category
    by_cat = {}
    for sig in analyzed_signals:
        cat = sig.get("category", "unknown")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(sig)
    
    # Troughs (green)
    if by_cat.get("trough"):
        lines.append("🟢 **ADD OPPORTUNITIES (Troughs)**:")
        for sig in by_cat["trough"]:
            sym = sig.get("symbol", "?")
            conf = sig.get("confidence", 0.0)
            narr = sig.get("narrative", "")[:100]
            target = sig.get("target", "")[:50]
            lines.append(f"  • {sym} (conf {conf:.1f}): {narr}")
            if target:
                lines.append(f"    → {target}")
        lines.append("")
    
    # Secular tops (warning)
    if by_cat.get("secular_top"):
        lines.append("⚠️ **THESIS REVIEWS (Secular Tops)**:")
        for sig in by_cat["secular_top"]:
            sym = sig.get("symbol", "?")
            conf = sig.get("confidence", 0.0)
            narr = sig.get("narrative", "")[:100]
            target = sig.get("target", "")[:50]
            lines.append(f"  • {sym} (conf {conf:.1f}): {narr}")
            if target:
                lines.append(f"    → {target}")
        lines.append("")
    
    # Momentum trims (red)
    if by_cat.get("momentum_trim"):
        lines.append("🔴 **TRIM PEAKS (Momentum)**:")
        for sig in by_cat["momentum_trim"]:
            sym = sig.get("symbol", "?")
            conf = sig.get("confidence", 0.0)
            narr = sig.get("narrative", "")[:100]
            strat = sig.get("target", "")[:50]
            lines.append(f"  • {sym} (conf {conf:.1f}): {narr}")
            if strat:
                lines.append(f"    → {strat}")
        lines.append("")
    
    # Portfolio insight
    if portfolio_insight:
        lines.append("📊 **Portfolio Insight**:")
        lines.append(portfolio_insight[:300])
        lines.append("")
    
    return "\n".join(lines).strip()


# ============================ MAIN API ============================ #

def analyze_signals(signals: list[dict], deep_analysis: bool = False, 
                   portfolio: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Main entry point: analyze signals and return deep analysis.
    
    Signature:
        analyze_signals(signals: list[dict], deep_analysis: bool, 
                       portfolio: Optional[dict]) -> dict[str, Any]
    
    Args:
        signals: Raw signal list from detectors
        deep_analysis: If False, only analyze conf >= MIN_CONFIDENCE_FOR_ANALYSIS
        portfolio: Optional portfolio dict for portfolio-level insight
        
    Returns:
        Dict with keys:
            - analyzed_signals: list of analyzed signal dicts
            - portfolio_insight: str or None
            - message: formatted Telegram message
            - timestamp: ISO timestamp
    """
    if not OLLAMA_API_KEY:
        logger.warning("OLLAMA_API_KEY not set; returning signals unenriched")
        return {
            "analyzed_signals": signals,
            "portfolio_insight": None,
            "message": "No LLM analysis (OLLAMA_API_KEY not set)",
            "timestamp": datetime.now().isoformat(),
        }
    
    # Filter signals
    to_analyze = filter_signals_for_analysis(signals, deep_analysis)
    if not to_analyze:
        logger.info("No signals meet analysis threshold")
        return {
            "analyzed_signals": [],
            "portfolio_insight": None,
            "message": "No signals warrant deep analysis",
            "timestamp": datetime.now().isoformat(),
        }
    
    analyzed = []
    portfolio_insight = None
    
    try:
        with OllamaPrimaryClient(OLLAMA_API_KEY) as client:
            # Analyze signals
            analyzed = client.analyze_batch(to_analyze)
            
            # Portfolio insight
            if portfolio:
                logger.info("Generating portfolio-level insight...")
                portfolio_insight = client.portfolio_insight(analyzed, portfolio)
    
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        analyzed = to_analyze  # Return raw if LLM fails
    
    # Format output
    message = format_telegram_message(analyzed, portfolio_insight)
    
    return {
        "analyzed_signals": analyzed,
        "portfolio_insight": portfolio_insight,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }


def analyze_single_signal(signal: dict, force: bool = False) -> Optional[dict]:
    """Analyze a single signal.
    
    Signature:
        analyze_single_signal(signal: dict, force: bool) -> Optional[dict]
    """
    if not should_analyze_signal(signal, force):
        return signal  # Return unenriched
    
    if not OLLAMA_API_KEY:
        logger.warning("OLLAMA_API_KEY not set")
        return signal
    
    try:
        with OllamaPrimaryClient(OLLAMA_API_KEY) as client:
            return client.analyze_signal(signal)
    except Exception as e:
        logger.error(f"Single signal analysis failed: {e}")
        return signal


# ============================ CLI ============================ #

def main(argv=None):
    """Command-line interface.
    
    USAGE:
        python -m charlotte.ollama_deep_analyzer --signal <json-signal-str>
        python -m charlotte.ollama_deep_analyzer --signals <json-array-str> [--deep-analysis]
        python -m charlotte.ollama_deep_analyzer --trough SHOP 3.1
        python -m charlotte.ollama_deep_analyzer --secular-top COIN 9.8
    """
    ap = argparse.ArgumentParser(
        description="Charlotte v4 LLM Deep Analyzer (Ollama Cloud)"
    )
    ap.add_argument("--signal", type=str, help="Single signal as JSON string")
    ap.add_argument("--signals", type=str, help="Signal array as JSON string")
    ap.add_argument("--trough", nargs=2, metavar=("SYMBOL", "CONFIDENCE"), 
                    help="Quick trough signal: symbol and confidence")
    ap.add_argument("--secular-top", nargs=2, metavar=("SYMBOL", "CONFIDENCE"),
                    help="Quick secular-top signal: symbol and confidence")
    ap.add_argument("--momentum-trim", nargs=2, metavar=("SYMBOL", "CONFIDENCE"),
                    help="Quick momentum-trim signal: symbol and confidence")
    ap.add_argument("--deep-analysis", action="store_true",
                    help="Force analysis on all signals (bypass confidence threshold)")
    ap.add_argument("--portfolio", type=str, help="Portfolio dict as JSON")
    ap.add_argument("--dry-run", action="store_true", help="Print message without sending")
    ap.add_argument("--verbose", action="store_true", help="Verbose logging")
    
    args = ap.parse_args(argv)
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Build signal(s)
    signals = []
    
    if args.signal:
        try:
            signals = [json.loads(args.signal)]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse --signal: {e}")
            return 1
    
    elif args.signals:
        try:
            signals = json.loads(args.signals)
            if not isinstance(signals, list):
                signals = [signals]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse --signals: {e}")
            return 1
    
    elif args.trough:
        sig, conf = args.trough[0], float(args.trough[1])
        signals = [{
            "symbol": sig,
            "category": "trough",
            "confidence": conf,
            "reasons": ["CLI trough signal"],
            "current_price": "N/A",
            "add_pct": 10,
            "action": "add",
        }]
    
    elif args.secular_top:
        sig, conf = args.secular_top[0], float(args.secular_top[1])
        signals = [{
            "symbol": sig,
            "category": "secular_top",
            "confidence": conf,
            "reasons": ["CLI secular-top signal"],
            "current_price": "N/A",
            "trim_pct": 50,
            "action": "thesis_review",
        }]
    
    elif args.momentum_trim:
        sig, conf = args.momentum_trim[0], float(args.momentum_trim[1])
        signals = [{
            "symbol": sig,
            "category": "momentum_trim",
            "confidence": conf,
            "reasons": ["CLI momentum-trim signal"],
            "current_price": "N/A",
            "trim_pct": 30,
            "trail_pct": 10.0,
            "action": "TRIM",
        }]
    
    else:
        ap.print_help()
        return 1
    
    # Parse portfolio if provided
    portfolio = None
    if args.portfolio:
        try:
            portfolio = json.loads(args.portfolio)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse --portfolio: {e}")
            return 1
    
    # Run analysis
    logger.info(f"Analyzing {len(signals)} signal(s)...")
    result = analyze_signals(signals, args.deep_analysis, portfolio)
    
    # Output
    if args.dry_run:
        print(json.dumps(result, indent=2))
    else:
        print(result["message"])
        if result.get("analyzed_signals"):
            print("\n[Raw JSON]")
            print(json.dumps({
                "signals": result["analyzed_signals"],
                "portfolio_insight": result["portfolio_insight"],
            }, indent=2))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
