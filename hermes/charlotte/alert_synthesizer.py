#!/usr/bin/env python3
"""Charlotte alert synthesizer v4 (LLM-enriched).
Runs all 3 detectors, scores, dedupes, optionally enriches with Ollama Cloud LLM.
Replaces sell-alert-synthesizer.py. Same cron schedule.

NEW: --deep-analysis flag to activate v4 LLM layer (ollama_deep_analyzer).
Default: deep_analysis=False (preserve Ollama Cloud resources during backtests).
LLM activates on LIVE SIGNALS (confidence >= 6.0) or explicit --deep-analysis.
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

ROOT = Path(__file__).resolve().parent.parent  # .../hermes
VENV_PY = "/tmp/trading-dashboard/backend/.venv/bin/python3"
DEDUP_FILE = "/tmp/charlotte-alerts-sent.json"
SNAPTRADE_PULL = "/tmp/snaptrade_pull.py"
MIN_CONFIDENCE = 6.0
DEEP_ANALYSIS_DEFAULT = False  # Flag to control LLM layer activation


def is_market_open_today():
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar('NYSE')
        today = datetime.now().date()
        valid = nyse.valid_days(start_date=today.isoformat(), end_date=today.isoformat())
        return len(valid) > 0
    except (ImportError, ValueError) as e:
        print(f"Market cal check failed: {e}", file=sys.stderr)
        return True


def get_portfolio():
    try:
        r = subprocess.run([VENV_PY, SNAPTRADE_PULL], capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            print(f"snaptrade rc={r.returncode}: {r.stderr}", file=sys.stderr)
            return {}
        data = json.loads(r.stdout)
        return {h['symbol']: h['quantity'] for h in data.get('holdings', [])}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
        print(f"portfolio error: {e}", file=sys.stderr)
        return {}


def run_detector(module, symbols, force=False):
    cmd = [VENV_PY, "-m", f"charlotte.{module}", "--symbol"] + symbols
    if force:
        cmd.append("--force")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(ROOT),
                           env={**__import__('os').environ, 'PYTHONPATH': str(ROOT)})
        if r.returncode != 0:
            print(f"{module} rc={r.returncode}: {r.stderr[-400:]}", file=sys.stderr)
            return []
        return json.loads(r.stdout or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"{module} error: {e}", file=sys.stderr)
        return []


def _tags(reasons):
    out = set()
    for r in reasons:
        low = r.lower()
        if 'rsi' in low: out.add('rsi')
        if 'macd' in low: out.add('macd')
        if 'vol' in low or 'capitulat' in low: out.add('vol')
        if 'adx' in low: out.add('adx')
        if 'sma' in low or '200' in low: out.add('sma')
        if 'rev' in low: out.add('rev')
        if 'downgrade' in low: out.add('downgrade')
        if 'p/e' in low or 'pe' == low[:2]: out.add('pe')
        if 'weekly' in low: out.add('weekly')
        if 'div' in low: out.add('div')
    return '|'.join(sorted(out))


def dedup_key(sig):
    return f"{sig['symbol']}:{sig['category']}:{_tags(sig.get('reasons', []))}"


def load_dedup():
    try:
        with open(DEDUP_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    cutoff = datetime.now() - timedelta(hours=48)
    return {k: v for k, v in data.items()
            if datetime.fromisoformat(v) >= cutoff}


def save_dedup(d):
    try:
        with open(DEDUP_FILE, 'w') as f:
            json.dump(d, f)
    except OSError as e:
        print(f"dedup save error: {e}", file=sys.stderr)


def filter_dedup(sigs, dedup):
    cutoff = datetime.now() - timedelta(hours=24)
    out = []
    for s in sigs:
        k = dedup_key(s)
        prev = dedup.get(k)
        if prev and datetime.fromisoformat(prev) >= cutoff:
            continue
        out.append(s)
    return out


def format_line(sig):
    sym = sig['symbol']
    reasons = ' + '.join(sig['reasons'])
    conf = sig['confidence']
    if sig['category'] == 'momentum_trim':
        return f"{sym} TRIM: {reasons}. Trim {sig['trim_pct']}%. Trail core at {sig['trail_pct']}%. Multi-factor confidence: {conf:.1f}/10"
    if sig['category'] == 'secular_top':
        return f"{sym} SECULAR-REVIEW: {reasons}. Trim {sig['trim_pct']}% + thesis check. Multi-factor confidence: {conf:.1f}/10"
    if sig['category'] == 'trough':
        return f"{sym} ADD: {reasons}. Add {sig['add_pct']}% to core. Multi-factor confidence: {conf:.1f}/10"
    return f"{sym}: {reasons} (conf {conf:.1f})"


def build_message(buckets):
    if not any(buckets.values()):
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    lines = [f"🕷️ Charlotte — {now}", ""]
    if buckets['momentum_trim']:
        lines.append("🔴 TRIMS (momentum peaks):")
        for s in buckets['momentum_trim']:
            lines.append(format_line(s))
        lines.append("")
    if buckets['secular_top']:
        lines.append("⚠️ SECULAR REVIEWS:")
        for s in buckets['secular_top']:
            lines.append(format_line(s))
        lines.append("")
    if buckets['trough']:
        lines.append("🟢 TROUGHS (add opportunities):")
        for s in buckets['trough']:
            lines.append(format_line(s))
        lines.append("")
    return "\n".join(lines).strip()


def enrich_signals_with_llm(signals, portfolio, deep_analysis=False):
    """Enrich signals with Ollama Cloud LLM analysis.
    
    Signature:
        enrich_signals_with_llm(signals: list[dict], portfolio: dict,
                               deep_analysis: bool) -> Tuple[list[dict], Optional[str]]
    
    Args:
        signals: List of raw detector signals
        portfolio: Portfolio dict for context
        deep_analysis: Force LLM analysis (bypass confidence threshold)
        
    Returns:
        Tuple of (signals, portfolio_insight) where signals may be enriched with LLM data
        Falls back to raw signals if LLM fails or unavailable.
    """
    try:
        from charlotte import ollama_deep_analyzer as lla
        result = lla.analyze_signals(signals, deep_analysis=deep_analysis, portfolio=portfolio)
        return result.get("analyzed_signals", signals), result.get("portfolio_insight")
    except (ImportError, ModuleNotFoundError):
        # LLM module not available; return signals as-is
        return signals, None
    except Exception as e:
        print(f"LLM enrichment failed (continuing without): {e}", file=sys.stderr)
        return signals, None


def send_telegram(msg):
    try:
        r = subprocess.run(["hermes", "send", "--to", "telegram", msg],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            print(f"hermes send rc={r.returncode}: {r.stderr}", file=sys.stderr)
            return False
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"telegram error: {e}", file=sys.stderr)
        return False


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='*', help='Override portfolio with explicit list')
    ap.add_argument('--force', action='store_true', help='Lower detector thresholds')
    ap.add_argument('--min-conf', type=float, default=MIN_CONFIDENCE)
    ap.add_argument('--dry-run', action='store_true', help='Print message; do not send/dedup')
    ap.add_argument('--deep-analysis', action='store_true', default=DEEP_ANALYSIS_DEFAULT,
                    help='Activate v4 LLM enrichment (Ollama Cloud)')
    args = ap.parse_args(argv)

    if not args.symbols and not is_market_open_today():
        print("Market closed today.", file=sys.stderr)
        return

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
        portfolio = {s: 0 for s in symbols}
    else:
        portfolio = get_portfolio()
        if not portfolio:
            print("No portfolio.", file=sys.stderr); return
        symbols = list(portfolio.keys())

    print(f"Scanning {len(symbols)} symbols...", file=sys.stderr)
    mt = run_detector('momentum_trim_detector', symbols, args.force)
    st = run_detector('secular_top_detector', symbols, args.force)
    tr = run_detector('trough_detector', symbols, args.force)

    all_sigs = mt + st + tr
    # Confidence floor
    all_sigs = [s for s in all_sigs if s.get('confidence', 0) >= args.min_conf]

    dedup = {} if args.dry_run else load_dedup()
    if not args.dry_run:
        all_sigs = filter_dedup(all_sigs, dedup)

    # LLM enrichment (v4 layer)
    if args.deep_analysis and all_sigs:
        print(f"Enriching signals with Ollama Cloud LLM...", file=sys.stderr)
        all_sigs, portfolio_insight = enrich_signals_with_llm(all_sigs, portfolio, args.deep_analysis)
    else:
        portfolio_insight = None

    buckets = {'momentum_trim': [], 'secular_top': [], 'trough': []}
    for s in all_sigs:
        buckets[s['category']].append(s)
    for k in buckets:
        buckets[k].sort(key=lambda x: -x['confidence'])

    msg = build_message(buckets)
    if not msg:
        print("No actionable signals.", file=sys.stderr)
        return
    
    # Append portfolio insight if available
    if portfolio_insight:
        msg += f"\n\n📊 **Portfolio Insight**:\n{portfolio_insight[:500]}"
    
    print(msg)
    if args.dry_run:
        return
    if send_telegram(msg):
        now_iso = datetime.now().isoformat()
        for s in all_sigs:
            dedup[dedup_key(s)] = now_iso
        save_dedup(dedup)


if __name__ == '__main__':
    main()
