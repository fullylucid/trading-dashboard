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


def build_income(chain: Chain, exp: str, kind: str) -> List[IncomeTrade]:
    """OTM premium sells. kind='put' -> cash-secured puts; kind='call' -> covered calls."""
    legs = [c for c in chain.for_exp(exp, kind) if c.mid > 0]
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
                    max_width: float = 0.0) -> List[Vertical]:
    legs = sorted(chain.for_exp(exp, kind), key=lambda c: c.strike)
    legs = [c for c in legs if c.mid > 0]
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
