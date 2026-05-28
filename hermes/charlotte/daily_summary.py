#!/usr/bin/env python3
"""Charlotte daily summary — zero-LLM, prints to stdout for cron->Telegram.

Silent watchdog: prints NOTHING if nothing changed. The shell wrapper feeds
stdout directly into Telegram, so silence = no alert.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Add hermes to path for absolute imports
sys.path.insert(0, '/tmp/trading-dashboard/hermes')

from charlotte.data_fetch import spy_bull_regime
from charlotte import trough_detector, secular_top_detector, momentum_trim_detector

FALLBACK_UNIVERSE = ["AMD", "NOW", "PLTR", "NVDA", "SMCI", "CELH",
                     "AAPL", "MSFT", "META", "TSLA"]
SNAPTRADE_PULL = "/tmp/snaptrade_pull.py"
ET = ZoneInfo("America/New_York")


def load_holdings(max_symbols: int) -> list[str]:
    """Return top-N symbols by position size from SnapTrade, or fallback."""
    if not os.path.exists(SNAPTRADE_PULL):
        print("[holdings] snaptrade_pull.py missing — using fallback universe",
              file=sys.stderr)
        return FALLBACK_UNIVERSE[:max_symbols]
    try:
        r = subprocess.run(
            [sys.executable, SNAPTRADE_PULL],
            capture_output=True, text=True, timeout=25,
        )
        data = json.loads(r.stdout.strip().splitlines()[-1])
        if "error" in data or "holdings" not in data:
            raise ValueError(data.get("error", "no holdings key"))
        rows = sorted(data["holdings"],
                      key=lambda x: -float(x.get("market_value", 0) or 0))
        syms = [h["symbol"] for h in rows if h.get("symbol")][:max_symbols]
        if not syms:
            raise ValueError("empty holdings")
        return syms
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError,
            json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"[holdings] snaptrade failed ({e}) — using fallback", file=sys.stderr)
        return FALLBACK_UNIVERSE[:max_symbols]


def scan_momentum(symbols: list[str]) -> list[dict]:
    out = []
    for s in symbols:
        try:
            r = momentum_trim_detector.analyze(s)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError) as e:
            print(f"[momentum {s}] {e}", file=sys.stderr)
            continue
        if r:
            out.append(r)
    return sorted(out, key=lambda x: -x["confidence"])


def load_state(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[state] load failed: {e}", file=sys.stderr)
        return {}


def save_state(path: str, state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print(f"[state] save failed: {e}", file=sys.stderr)


def _topn(rows: list[dict], n: int) -> list[dict]:
    return [{"symbol": r["symbol"], "conf": round(float(r["confidence"]), 2)}
            for r in rows[:n]]


def _diff_top(prev: list[dict], curr: list[dict]) -> dict:
    """Return diff: new, dropped, shifted (>=0.5 conf), unchanged."""
    pmap = {r["symbol"]: r["conf"] for r in prev}
    cmap = {r["symbol"]: r["conf"] for r in curr}
    new = [s for s in cmap if s not in pmap]
    dropped = [s for s in pmap if s not in cmap]
    shifted = []
    for s, c in cmap.items():
        if s in pmap and abs(c - pmap[s]) >= 0.5:
            shifted.append((s, pmap[s], c))
    return {"new": new, "dropped": dropped, "shifted": shifted}


def _fmt_row(curr: list[dict], prev: list[dict]) -> str:
    pmap = {r["symbol"]: r["conf"] for r in prev}
    parts = []
    for r in curr:
        s, c = r["symbol"], r["conf"]
        if s in pmap:
            d = c - pmap[s]
            tag = "(=)" if abs(d) < 0.5 else f"({d:+.1f})"
        else:
            tag = "(NEW)"
        parts.append(f"{s} {c:.1f} {tag}")
    return "   ".join(parts)


def build_report(state_path: str, max_symbols: int) -> tuple[str, dict]:
    bull, info = spy_bull_regime()
    regime = "bull" if bull else "bear"

    holdings = load_holdings(max_symbols)
    print(f"[scan] universe ({len(holdings)}): {','.join(holdings)}", file=sys.stderr)

    trough_rows = trough_detector.detect(holdings)
    secular_rows = secular_top_detector.detect(holdings)
    momentum_rows = scan_momentum(holdings)

    trough_top = _topn(trough_rows, 5)
    secular_top = _topn(secular_rows, 3)

    prev = load_state(state_path)
    prev_regime = prev.get("regime")
    prev_trough = prev.get("trough_top", [])
    prev_secular = prev.get("secular_top", [])

    regime_flip = prev_regime is not None and prev_regime != regime
    trough_diff = _diff_top(prev_trough, trough_top)
    secular_diff = _diff_top(prev_secular, secular_top)

    has_momentum = len(momentum_rows) > 0
    has_trough_change = bool(trough_diff["new"] or trough_diff["dropped"]
                             or trough_diff["shifted"])
    has_secular_change = bool(secular_diff["new"] or secular_diff["dropped"]
                              or secular_diff["shifted"])

    new_state = {
        "date": datetime.now(ET).strftime("%Y-%m-%d"),
        "regime": regime,
        "trough_top": trough_top,
        "secular_top": secular_top,
        "momentum_fires": [r["symbol"] for r in momentum_rows],
    }

    # Silent watchdog: nothing notable -> empty output
    if not (regime_flip or has_momentum or has_trough_change
            or has_secular_change or prev_regime is None):
        return "", new_state

    date_str = datetime.now(ET).strftime("%Y-%m-%d")
    lines = [f"🕷️ Charlotte daily — {date_str} ET", ""]

    if regime_flip:
        new_thr = 3 if not bull else 4
        old_thr = 4 if not bull else 3
        lines.append(
            f"⚠️ REGIME FLIP: {prev_regime.upper()} → {regime.upper()} — "
            f"momentum_trim pillars {old_thr} → {new_thr}"
        )
    else:
        if bull:
            lines.append(
                f"Regime: BULL ✅ (SPY ${info.get('spy_close', 0):.0f} > "
                f"200SMA ${info.get('sma200', 0):.0f}, "
                f"slope {info.get('slope20', 0):+.2f})"
            )
        else:
            lines.append(
                f"Regime: BEAR 🔻 (SPY ${info.get('spy_close', 0):.0f} vs "
                f"200SMA ${info.get('sma200', 0):.0f}, "
                f"slope {info.get('slope20', 0):+.2f})"
            )
    lines.append("")

    lines.append(f"Momentum trim: {len(momentum_rows)} fires today")
    if momentum_rows:
        for r in momentum_rows:
            reasons = "+".join(r.get("reasons", []))
            lines.append(
                f"  • {r['symbol']} {r['confidence']:.1f} — {reasons} → "
                f"trim {r['trim_pct']}%, trail {r['trail_pct']}%"
            )
    else:
        lines.append("  (bull regime gate holding)" if bull else "  (none)")
    lines.append("")

    if has_trough_change or prev_regime is None:
        lines.append("Trough top-5 (Δ vs yesterday):")
        if trough_top:
            lines.append("🟢 " + _fmt_row(trough_top, prev_trough))
        else:
            lines.append("  (no trough candidates)")
        if trough_diff["dropped"]:
            lines.append(f"   DROPPED: {', '.join(trough_diff['dropped'])}")
        lines.append("")

    if has_secular_change or prev_regime is None:
        lines.append("Secular top-3 (Δ):")
        if secular_top:
            lines.append("🔻 " + _fmt_row(secular_top, prev_secular))
        else:
            lines.append("  (no secular-top candidates)")
        if secular_diff["dropped"]:
            lines.append(f"   DROPPED: {', '.join(secular_diff['dropped'])}")
        lines.append("")

    lines.append("_Cron: 16:30 ET Mon-Fri · v3.1_")
    return "\n".join(lines).rstrip() + "\n", new_state


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", required=True, help="Path to JSON state file")
    p.add_argument("--max-symbols", type=int, default=20)
    args = p.parse_args()

    try:
        report, new_state = build_report(args.state, args.max_symbols)
    except (ValueError, KeyError, AttributeError, IndexError, TypeError,
            OSError, RuntimeError) as e:
        print(f"[fatal] {type(e).__name__}: {e}", file=sys.stderr)
        return 0  # silent on failure — no Telegram noise

    if report:
        sys.stdout.write(report)
        sys.stdout.flush()
    save_state(args.state, new_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
