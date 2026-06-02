"""
opts — options CLI. Full chains + Greeks (yfinance), strategy formulation, your real
positions (SnapTrade), and a hard-disabled trade path.

    python -m options_cli chain NOW
    python -m options_cli strategy NOW --kind call --dir bull
    python -m options_cli positions
    python -m options_cli trade --action BUY_TO_OPEN --contract "NOW 2026-06-18 110C" --qty 1 --limit 4.20
"""
from __future__ import annotations

import argparse
import sys

from . import account, trade
from .chains import get_chain
from .strategies import build_verticals, build_income, build_iron_condor, build_strangle, build_straddle
from .wheel import wheel_status


def _near(contracts, spot, n):
    return sorted(contracts, key=lambda c: abs(c.strike - spot))[:n]


def cmd_chain(a) -> int:
    ch = get_chain(a.symbol, expirations=[a.exp] if a.exp else None, max_exps=1 if a.exp else 4)
    if not ch.contracts:
        print(f"No options for {a.symbol}.")
        return 1
    exp = a.exp or ch.expirations[0]
    print(f"{ch.symbol}  spot ${ch.spot:.2f}  rate {ch.rate*100:.2f}%  exp {exp}  "
          f"(expirations available: {len(ch.expirations)})")
    print(f"{'TYPE':<4}{'STRIKE':>8}{'BID':>7}{'ASK':>7}{'MID':>7}{'IV':>7}"
          f"{'VOL':>7}{'OI':>8}{'Δ':>7}{'Θ':>7}{'P(ITM)':>8}")
    for kind in ("call", "put"):
        for c in sorted(_near(ch.for_exp(exp, kind), ch.spot, a.near), key=lambda c: c.strike):
            print(f"{kind:<4}{c.strike:>8g}{c.bid:>7.2f}{c.ask:>7.2f}{c.mid:>7.2f}"
                  f"{c.iv*100:>6.0f}%{c.volume:>7}{c.open_interest:>8}"
                  f"{c.greeks.delta:>7.2f}{c.greeks.theta:>7.2f}{c.greeks.prob_itm*100:>7.0f}%")
    return 0


def cmd_strategy(a) -> int:
    ch = get_chain(a.symbol, expirations=[a.exp] if a.exp else None,
                   max_exps=1, target_dte=None if a.exp else a.dte)
    exp = a.exp or (ch.contracts[0].expiration if ch.contracts else None)
    if not exp:
        print(f"No options for {a.symbol}."); return 1
    verts = build_verticals(ch, exp, a.kind, a.dir, max_width=a.width)
    if not verts:
        print("No valid spreads (illiquid strikes?)."); return 1
    print(f"{ch.symbol}  spot ${ch.spot:.2f}  exp {exp} — top {a.kind} {a.dir} verticals "
          f"(ranked by reward:risk × POP)")
    print(f"{'SPREAD':<20}{'TYPE':>7}{'NET':>8}{'MAXP':>8}{'MAXL':>8}{'B/E':>9}{'R:R':>6}{'POP':>7}{'SCORE':>7}")
    for v in verts[:a.top]:
        net = f"+{v.net:.2f}" if v.debit_credit == "debit" else f"-{-v.net:.2f}"
        print(f"{v.label:<20}{v.debit_credit:>7}{net:>8}{v.max_profit:>8.2f}{v.max_loss:>8.2f}"
              f"{v.breakeven:>9.2f}{v.rr:>6.2f}{v.pop*100:>6.0f}%{v.score:>7.2f}")
    return 0


def cmd_income(a) -> int:
    ch = get_chain(a.symbol, expirations=[a.exp] if a.exp else None,
                   max_exps=1, target_dte=None if a.exp else a.dte)
    exp = a.exp or (ch.contracts[0].expiration if ch.contracts else None)
    if not exp:
        print(f"No options for {a.symbol}."); return 1
    trades = build_income(ch, exp, a.kind)
    if not trades:
        print("No liquid sells in the sellable range."); return 1
    name = "cash-secured puts" if a.kind == "put" else "covered calls"
    print(f"{ch.symbol}  spot ${ch.spot:.2f}  exp {exp} — top {name} (ranked by ann.yield × POP)")
    print(f"{'STRIKE':>7}{'PREM':>8}{'B/E':>9}{'POP':>7}{'ANN.YLD':>9}{'CUSHION':>9}{'Θ/day':>8}")
    for t in trades[:a.top]:
        print(f"{t.strike:>7g}{t.premium:>8.2f}{t.breakeven:>9.2f}{t.pop*100:>6.0f}%"
              f"{t.annual_yield*100:>8.0f}%{t.cushion*100:>8.1f}%{t.theta:>+8.2f}")
    return 0


def _multileg(symbol, exp, dte, builder, *bargs):
    ch = get_chain(symbol, expirations=[exp] if exp else None,
                   max_exps=1, target_dte=None if exp else dte)
    use = exp or (ch.contracts[0].expiration if ch.contracts else None)
    if not use:
        print(f"No options for {symbol}."); return None, None
    return ch, builder(ch, use, *bargs)


def _print_multileg(ch, items, title):
    if not items:
        print("None found (need liquid OTM strikes on both sides — try SPY/QQQ/AAPL)."); return 1
    exp = ch.contracts[0].expiration if ch.contracts else "?"
    print(f"{ch.symbol}  spot ${ch.spot:.2f}  exp {exp} — {title}")
    print(f"{'STRUCTURE':<30}{'NET':>9}{'MAXP':>8}{'MAXL':>9}{'POP':>7}  breakevens")
    for m in items:
        net = f"+{m.net:.2f}" if m.net >= 0 else f"-{-m.net:.2f}"
        maxl = "inf*" if m.undefined_risk else f"{m.max_loss:.2f}"
        print(f"{m.label:<30}{net:>9}{m.max_profit:>8.2f}{maxl:>9}{m.pop*100:>6.0f}%  "
              f"{' / '.join(f'{b:.1f}' for b in m.breakevens)}")
    return 0


def cmd_condor(a) -> int:
    ch, items = _multileg(a.symbol, a.exp, a.dte, build_iron_condor)
    return 1 if ch is None else _print_multileg(ch, items, "iron condors (range-bound income)")


def cmd_strangle(a) -> int:
    ch, items = _multileg(a.symbol, a.exp, a.dte, build_strangle, a.side)
    return 1 if ch is None else _print_multileg(ch, items, f"{a.side} strangles")


def cmd_straddle(a) -> int:
    ch, items = _multileg(a.symbol, a.exp, a.dte, build_straddle, a.side)
    return 1 if ch is None else _print_multileg(ch, items, f"{a.side} straddle")


def cmd_wheel(a) -> int:
    w = wheel_status(a.symbol)
    if w.get("error"):
        print(f"{a.symbol}: {w['error']}"); return 1
    phase = "COVERED CALL (you hold shares)" if w["phase"] == "covered_call" else "CASH-SECURED PUT (no shares)"
    print(f"🎡 The Wheel — {w['symbol']}  spot ${w['spot']:.2f}  ({w['shares_held']:.0f} shares held)")
    print(f"You are at: {phase}\n→ {w['next_move']}\n")
    print(f"Suggested {('covered calls' if w['phase']=='covered_call' else 'cash-secured puts')} (exp {w['expiration']}):")
    print(f"{'STRIKE':>7}{'PREM':>8}{'B/E':>9}{'POP':>7}{'ANN.YLD':>9}{'CUSHION':>9}")
    for s in w["suggestions"]:
        print(f"{s['strike']:>7g}{s['premium']:>8.2f}{s['breakeven']:>9.2f}{s['pop']*100:>6.0f}%"
              f"{s['annual_yield']*100:>8.0f}%{s['cushion']*100:>8.1f}%")
    return 0


def cmd_positions(_a) -> int:
    pos = account.option_positions()
    if not pos:
        print("No option positions (or none surfaced by the broker feed)."); return 0
    print(f"{'CONTRACT':<28}{'QTY':>6}{'VALUE':>12}{'UNREAL P/L':>12}")
    for p in pos:
        print(f"{str(p['symbol'])[:28]:<28}{str(p.get('quantity','')):>6}"
              f"{(p.get('value') or 0):>12,.0f}{(p.get('unrealized_pl') or 0):>12,.0f}")
    return 0


def cmd_trade(a) -> int:
    prop = trade.OrderProposal(action=a.action, contract=a.contract, quantity=a.qty,
                               limit=a.limit, note=a.note or "")
    print(trade.submit(prop, confirm=a.confirm))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="opts", description="Options chains, Greeks, strategies, (gated) trades")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chain", help="full chain + Greeks"); c.add_argument("symbol")
    c.add_argument("--exp"); c.add_argument("--near", type=int, default=8); c.set_defaults(fn=cmd_chain)

    s = sub.add_parser("strategy", help="formulate vertical spreads"); s.add_argument("symbol")
    s.add_argument("--kind", choices=["call", "put"], default="call")
    s.add_argument("--dir", choices=["bull", "bear"], default="bull")
    s.add_argument("--exp"); s.add_argument("--width", type=float, default=0.0)
    s.add_argument("--dte", type=int, default=30); s.add_argument("--top", type=int, default=8)
    s.set_defaults(fn=cmd_strategy)

    i = sub.add_parser("income", help="cash-secured puts (--kind put) / covered calls (--kind call)")
    i.add_argument("symbol"); i.add_argument("--kind", choices=["put", "call"], default="put")
    i.add_argument("--exp"); i.add_argument("--dte", type=int, default=30)
    i.add_argument("--top", type=int, default=8); i.set_defaults(fn=cmd_income)

    co = sub.add_parser("condor", help="iron condors (range-bound income)")
    co.add_argument("symbol"); co.add_argument("--exp"); co.add_argument("--dte", type=int, default=30)
    co.set_defaults(fn=cmd_condor)

    sg = sub.add_parser("strangle", help="strangle (--side short=income / long=volatility)")
    sg.add_argument("symbol"); sg.add_argument("--side", choices=["short", "long"], default="short")
    sg.add_argument("--exp"); sg.add_argument("--dte", type=int, default=30); sg.set_defaults(fn=cmd_strangle)

    sd = sub.add_parser("straddle", help="straddle (--side long=move bet / short=premium)")
    sd.add_argument("symbol"); sd.add_argument("--side", choices=["long", "short"], default="long")
    sd.add_argument("--exp"); sd.add_argument("--dte", type=int, default=30); sd.set_defaults(fn=cmd_straddle)

    w = sub.add_parser("wheel", help="guided Wheel — where you are + the next trade")
    w.add_argument("symbol"); w.set_defaults(fn=cmd_wheel)

    sub.add_parser("positions", help="your option positions").set_defaults(fn=cmd_positions)

    t = sub.add_parser("trade", help="propose an order (execution hard-disabled)")
    t.add_argument("--action", required=True); t.add_argument("--contract", required=True)
    t.add_argument("--qty", type=int, default=1); t.add_argument("--limit", type=float, required=True)
    t.add_argument("--note", default=""); t.add_argument("--confirm", action="store_true")
    t.set_defaults(fn=cmd_trade)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
