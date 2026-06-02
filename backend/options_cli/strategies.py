"""
Strategy formulation off the live chain. v1: vertical spreads (the workhorse) with
net cost, max profit/loss, breakeven, reward:risk, and a principled probability of
profit (risk-neutral P(finish past breakeven) from the legs' IV).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

from . import greeks as _greeks
from .chains import Chain, Contract


@dataclass
class Vertical:
    label: str                # e.g. "bull call 100/110"
    kind: str                 # call | put
    direction: str            # bull | bear
    debit_credit: str         # debit | credit
    long: Contract
    short: Contract
    width: float
    net: float                # +debit paid / -credit received (per share)
    max_profit: float
    max_loss: float
    breakeven: float
    rr: float                 # reward : risk
    pop: float                # prob of profit (0..1)
    score: float = 0.0


def _pop_past(spot: float, level: float, t_years: float, iv: float,
              rate: float, bullish: bool) -> float:
    """Risk-neutral P(S_T beyond `level` in the profitable direction)."""
    g = _greeks.compute(spot, level, t_years, iv, rate=rate, is_call=bullish)
    return g.prob_itm  # N(d2) for a call = P(S_T>level); put = P(S_T<level)


@dataclass
class IncomeTrade:
    """A premium-selling trade: cash-secured put or covered call (single short leg)."""
    label: str
    type: str                 # cash_secured_put | covered_call
    strike: float
    premium: float            # credit received (per share)
    breakeven: float
    max_profit: float         # per share (premium; CC adds appreciation to the strike)
    pop: float                # P(expire OTM -> keep full premium)
    annual_yield: float       # premium/collateral annualized (fraction)
    cushion: float            # CSP: discount-to-spot if assigned; CC: downside cover (fraction)
    capital: float            # collateral per contract (CSP: strike*100; CC: 100 shares)
    delta: float
    theta: float
    dte: int
    score: float = 0.0


def build_income(chain: Chain, exp: str, kind: str, min_oi: int = 25,
                 delta_lo: float = 0.10, delta_hi: float = 0.45) -> List[IncomeTrade]:
    """OTM premium sells. kind='put' -> cash-secured puts; kind='call' -> covered calls.
    Filters to liquid (min_oi) contracts in the sellable delta band — the strikes you'd
    actually trade, not deep-ITM or far-OTM dust."""
    legs = [c for c in chain.for_exp(exp, kind)
            if c.mid > 0 and c.open_interest >= min_oi
            and delta_lo <= abs(c.greeks.delta) <= delta_hi]
    if not legs:
        return []
    dte = legs[0].dte
    tyr = max(dte / 365.0, 1e-6)
    yrs = max(dte, 1) / 365.0
    spot = chain.spot
    out: List[IncomeTrade] = []
    for c in legs:
        prem = c.mid
        if kind == "put":                       # cash-secured put (sell OTM put)
            if c.strike >= spot:
                continue
            be = c.strike - prem
            pop = _pop_past(spot, c.strike, tyr, c.iv, chain.rate, bullish=True)  # P(S>strike)
            yield_ = (prem / c.strike) / yrs
            cushion = (spot - be) / spot         # how far below spot before you lose
            cap = c.strike * 100
            t = IncomeTrade(f"CSP {c.strike:g}", "cash_secured_put", c.strike, prem, round(be, 2),
                            prem, round(pop, 3), round(yield_, 3), round(cushion, 3), cap,
                            round(-c.greeks.delta, 3), round(-c.greeks.theta, 3), dte)
        else:                                    # covered call (sell OTM call vs 100 shares)
            if c.strike <= spot:
                continue
            be = spot - prem
            pop = 1 - c.greeks.prob_itm          # P(call expires OTM -> keep shares + premium)
            if_called = (prem + (c.strike - spot)) / spot
            yield_ = if_called / yrs
            cushion = prem / spot                 # downside cover from premium
            cap = spot * 100
            t = IncomeTrade(f"CC {c.strike:g}", "covered_call", c.strike, prem, round(be, 2),
                            round(prem + (c.strike - spot), 2), round(pop, 3), round(yield_, 3),
                            round(cushion, 3), cap, round(-c.greeks.delta, 3),
                            round(-c.greeks.theta, 3), dte)
        # rank: annualized yield weighted by probability of keeping it
        t.score = round(t.annual_yield * t.pop, 3)
        out.append(t)
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def build_verticals(chain: Chain, exp: str, kind: str, direction: str,
                    max_width: float = 0.0, min_oi: int = 25,
                    moneyness: float = 0.25) -> List[Vertical]:
    """Filters to liquid (min_oi) legs within `moneyness` of spot — no deep-ITM
    penny spreads or illiquid wings."""
    band = moneyness * (chain.spot or 1)
    legs = sorted((c for c in chain.for_exp(exp, kind)
                   if c.mid > 0 and c.open_interest >= min_oi
                   and abs(c.strike - chain.spot) <= band), key=lambda c: c.strike)
    if len(legs) < 2:
        return []
    dte = legs[0].dte
    tyr = max(dte / 365.0, 1e-6)
    out: List[Vertical] = []
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            lo, hi = legs[i], legs[j]
            width = hi.strike - lo.strike
            if width <= 0 or (max_width and width > max_width):
                continue
            # assign long/short by strategy
            if kind == "call" and direction == "bull":      # debit: buy lo, sell hi
                long_, short_, dc = lo, hi, "debit"
            elif kind == "call" and direction == "bear":    # credit: sell lo, buy hi
                long_, short_, dc = hi, lo, "credit"
            elif kind == "put" and direction == "bear":     # debit: buy hi, sell lo
                long_, short_, dc = hi, lo, "debit"
            else:                                            # put bull -> credit: sell hi, buy lo
                long_, short_, dc = lo, hi, "credit"

            net = round(long_.mid - short_.mid, 2)           # +debit / -credit
            if dc == "debit":
                if net <= 0:
                    continue
                max_loss = net
                max_profit = round(width - net, 2)
                breakeven = (lo.strike + net) if kind == "call" else (hi.strike - net)
            else:  # credit
                credit = -net
                if credit <= 0:
                    continue
                max_profit = round(credit, 2)
                max_loss = round(width - credit, 2)
                breakeven = (lo.strike + credit) if kind == "call" else (hi.strike - credit)
            if max_loss <= 0 or max_profit <= 0:
                continue
            bullish = direction == "bull"
            iv = (long_.iv + short_.iv) / 2 or long_.iv or short_.iv
            pop = _pop_past(chain.spot, breakeven, tyr, iv, chain.rate, bullish)
            rr = round(max_profit / max_loss, 2)
            v = Vertical(
                label=f"{direction} {kind} {lo.strike:g}/{hi.strike:g}",
                kind=kind, direction=direction, debit_credit=dc,
                long=long_, short=short_, width=width, net=net,
                max_profit=max_profit, max_loss=max_loss, breakeven=round(breakeven, 2),
                rr=rr, pop=round(pop, 3),
            )
            v.score = round(rr * pop, 3)   # expected-value-ish rank
            out.append(v)
    out.sort(key=lambda v: v.score, reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Multi-leg structures: iron condor, strangle, straddle. They return their legs
# so the payoff is computed generically (sum of leg intrinsics ± premium).
# --------------------------------------------------------------------------- #
@dataclass
class Leg:
    action: str   # long | short
    kind: str     # call | put
    strike: float
    premium: float


@dataclass
class MultiLeg:
    label: str
    type: str                  # iron_condor | strangle | straddle
    side: str                  # credit/short | debit/long
    legs: List[Leg]
    net: float                 # +credit received / -debit paid (per share)
    max_profit: float          # per share (None-sentinel: large = "undefined/large")
    max_loss: float
    breakevens: List[float]
    pop: float
    undefined_risk: bool = False
    score: float = 0.0


def _nearest_delta(legs: List[Contract], target: float) -> Optional[Contract]:
    cand = [c for c in legs if c.mid > 0 and c.open_interest >= 10]
    return min(cand, key=lambda c: abs(abs(c.greeks.delta) - target)) if cand else None


def _nearest_strike(legs: List[Contract], strike: float) -> Optional[Contract]:
    cand = [c for c in legs if c.mid > 0]
    return min(cand, key=lambda c: abs(c.strike - strike)) if cand else None


def _between_pop(spot, lo, hi, tyr, iv, rate):
    return max(_pop_past(spot, lo, tyr, iv, rate, True) - _pop_past(spot, hi, tyr, iv, rate, True), 0.0)


def build_iron_condor(chain: Chain, exp: str, wing_pct: float = 0.06) -> List[MultiLeg]:
    """Sell an OTM put spread + an OTM call spread — range-bound income, defined risk."""
    puts = sorted(chain.for_exp(exp, "put"), key=lambda c: c.strike)
    calls = sorted(chain.for_exp(exp, "call"), key=lambda c: c.strike)
    if not puts or not calls:
        return []
    spot, rate = chain.spot, chain.rate
    dte = (puts or calls)[0].dte
    tyr = max(dte / 365.0, 1e-6)
    wing = max(wing_pct * spot, 1.0)
    out: List[MultiLeg] = []
    for tgt in (0.16, 0.20, 0.25, 0.30):
        sp = _nearest_delta([p for p in puts if p.strike < spot], tgt)
        sc = _nearest_delta([c for c in calls if c.strike > spot], tgt)
        if not sp or not sc:
            continue
        lp = _nearest_strike([p for p in puts if p.strike < sp.strike], sp.strike - wing)
        lc = _nearest_strike([c for c in calls if c.strike > sc.strike], sc.strike + wing)
        if not lp or not lc or lp.strike >= sp.strike or lc.strike <= sc.strike:
            continue
        credit = round((sp.mid - lp.mid) + (sc.mid - lc.mid), 2)
        if credit <= 0:
            continue
        pw, cw = sp.strike - lp.strike, lc.strike - sc.strike
        max_loss = round(max(pw, cw) - credit, 2)
        if max_loss <= 0:
            continue
        iv = (sp.iv + sc.iv) / 2
        pop = _between_pop(spot, sp.strike, sc.strike, tyr, iv, rate)
        m = MultiLeg(
            label=f"IC {lp.strike:g}/{sp.strike:g} - {sc.strike:g}/{lc.strike:g}",
            type="iron_condor", side="credit",
            legs=[Leg("long", "put", lp.strike, lp.mid), Leg("short", "put", sp.strike, sp.mid),
                  Leg("short", "call", sc.strike, sc.mid), Leg("long", "call", lc.strike, lc.mid)],
            net=credit, max_profit=credit, max_loss=max_loss,
            breakevens=[round(sp.strike - credit, 2), round(sc.strike + credit, 2)],
            pop=round(pop, 3))
        m.score = round((credit / max_loss) * pop, 3)
        out.append(m)
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def build_strangle(chain: Chain, exp: str, side: str = "short") -> List[MultiLeg]:
    """Short = sell OTM put+call (income, undefined risk). Long = buy OTM put+call (volatility bet)."""
    puts = chain.for_exp(exp, "put")
    calls = chain.for_exp(exp, "call")
    if not puts or not calls:
        return []
    spot, rate = chain.spot, chain.rate
    dte = (puts or calls)[0].dte
    tyr = max(dte / 365.0, 1e-6)
    out: List[MultiLeg] = []
    for tgt in (0.16, 0.25, 0.35):
        p = _nearest_delta([x for x in puts if x.strike < spot], tgt)
        c = _nearest_delta([x for x in calls if x.strike > spot], tgt)
        if not p or not c:
            continue
        iv = (p.iv + c.iv) / 2
        if side == "short":
            credit = round(p.mid + c.mid, 2)
            be = [round(p.strike - credit, 2), round(c.strike + credit, 2)]
            pop = _between_pop(spot, p.strike, c.strike, tyr, iv, rate)
            m = MultiLeg(f"short strangle {p.strike:g}P/{c.strike:g}C", "strangle", "credit",
                         [Leg("short", "put", p.strike, p.mid), Leg("short", "call", c.strike, c.mid)],
                         credit, credit, round(max(p.strike, c.strike), 2), be, round(pop, 3),
                         undefined_risk=True)
            m.score = round(credit * pop, 3)
        else:
            debit = round(p.mid + c.mid, 2)
            be = [round(p.strike - debit, 2), round(c.strike + debit, 2)]
            pop = round(1 - _between_pop(spot, be[0], be[1], tyr, iv, rate), 3)  # profit on a big move
            m = MultiLeg(f"long strangle {p.strike:g}P/{c.strike:g}C", "strangle", "debit",
                         [Leg("long", "put", p.strike, p.mid), Leg("long", "call", c.strike, c.mid)],
                         -debit, round(spot, 2), debit, be, pop)
            m.score = round(pop, 3)
        out.append(m)
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def build_straddle(chain: Chain, exp: str, side: str = "long") -> List[MultiLeg]:
    """ATM call + put. Long = pure volatility/big-move bet; short = max premium (risky)."""
    calls = chain.for_exp(exp, "call")
    puts = chain.for_exp(exp, "put")
    if not calls or not puts:
        return []
    spot, rate = chain.spot, chain.rate
    c = _nearest_strike(calls, spot)
    p = _nearest_strike([x for x in puts if abs(x.strike - (c.strike if c else spot)) < 1e-6] or puts, spot)
    if not c or not p:
        return []
    dte = c.dte
    tyr = max(dte / 365.0, 1e-6)
    iv = (c.iv + p.iv) / 2
    if side == "long":
        debit = round(c.mid + p.mid, 2)
        be = [round(c.strike - debit, 2), round(c.strike + debit, 2)]
        pop = round(1 - _between_pop(spot, be[0], be[1], tyr, iv, rate), 3)
        m = MultiLeg(f"long straddle {c.strike:g}", "straddle", "debit",
                     [Leg("long", "call", c.strike, c.mid), Leg("long", "put", p.strike, p.mid)],
                     -debit, round(spot, 2), debit, be, pop)
    else:
        credit = round(c.mid + p.mid, 2)
        be = [round(c.strike - credit, 2), round(c.strike + credit, 2)]
        pop = round(_between_pop(spot, be[0], be[1], tyr, iv, rate), 3)
        m = MultiLeg(f"short straddle {c.strike:g}", "straddle", "credit",
                     [Leg("short", "call", c.strike, c.mid), Leg("short", "put", p.strike, p.mid)],
                     credit, credit, round(c.strike, 2), be, pop, undefined_risk=True)
    return [m]
