"""
Full option chains from yfinance, enriched with computed Greeks.

This is the part SnapTrade can't do well: every contract across every strike and
expiration, with IV/OI/volume/bid-ask, plus Black-Scholes Greeks from the IV.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional

from . import greeks as _greeks
from .rates import risk_free

logger = logging.getLogger("options_cli.chains")


def _num(x) -> float:
    try:
        v = float(x)
        return 0.0 if math.isnan(v) else v
    except (TypeError, ValueError):
        return 0.0


def _int(x) -> int:
    return int(_num(x))


@dataclass
class Contract:
    symbol: str
    expiration: str
    strike: float
    kind: str            # "call" | "put"
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    iv: float            # implied vol (fraction)
    dte: int             # days to expiration
    greeks: _greeks.Greeks
    mid: float = 0.0

    def __post_init__(self):
        self.mid = round((self.bid + self.ask) / 2, 2) if (self.bid and self.ask) else self.last


@dataclass
class Chain:
    symbol: str
    spot: float
    rate: float
    expirations: List[str]
    contracts: List[Contract] = field(default_factory=list)

    def for_exp(self, exp: str, kind: Optional[str] = None) -> List[Contract]:
        return [c for c in self.contracts
                if c.expiration == exp and (kind is None or c.kind == kind)]


def _spot(t) -> float:
    try:
        return float(t.fast_info.last_price)
    except Exception:  # noqa: BLE001
        h = t.history(period="1d")
        return float(h["Close"].iloc[-1]) if not h.empty else 0.0


def pick_expiration(expirations: List[str], target_dte: int) -> Optional[str]:
    """The listed expiration whose days-to-expiration is closest to target_dte."""
    today = dt.date.today()
    if not expirations:
        return None
    return min(expirations,
               key=lambda e: abs((dt.date.fromisoformat(e) - today).days - target_dte))


def get_chain(symbol: str, expirations: Optional[List[str]] = None,
              max_exps: int = 6, target_dte: Optional[int] = None) -> Chain:
    """Fetch the chain. With target_dte (and no explicit expirations), default to the
    expiration nearest that many days out — a realistic monthly, not the nearest weekly."""
    import yfinance as yf

    symbol = symbol.upper()
    t = yf.Ticker(symbol)
    all_exps = list(t.options or [])
    if not all_exps:
        return Chain(symbol, 0.0, risk_free(), [])
    spot = _spot(t)
    rate = risk_free()
    if expirations:
        target = expirations
    elif target_dte is not None:
        pick = pick_expiration(all_exps, target_dte)
        target = [pick] if pick else all_exps[:max_exps]
    else:
        target = all_exps[:max_exps]
    today = dt.date.today()

    contracts: List[Contract] = []
    for exp in target:
        if exp not in all_exps:
            continue
        try:
            oc = t.option_chain(exp)
        except Exception as e:  # noqa: BLE001
            logger.warning("chain fetch failed for %s %s: %s", symbol, exp, e)
            continue
        dte = max((dt.date.fromisoformat(exp) - today).days, 0)
        tyr = max(dte / 365.0, 1e-6)
        for kind, df in (("call", oc.calls), ("put", oc.puts)):
            for _, r in df.iterrows():
                iv = _num(r.get("impliedVolatility"))
                strike = _num(r.get("strike"))
                g = _greeks.compute(spot, strike, tyr, iv, rate=rate, is_call=(kind == "call"))
                contracts.append(Contract(
                    symbol=symbol, expiration=exp, strike=strike, kind=kind,
                    bid=_num(r.get("bid")), ask=_num(r.get("ask")), last=_num(r.get("lastPrice")),
                    volume=_int(r.get("volume")), open_interest=_int(r.get("openInterest")),
                    iv=iv, dte=dte, greeks=g,
                ))
    return Chain(symbol, spot, rate, all_exps, contracts)
