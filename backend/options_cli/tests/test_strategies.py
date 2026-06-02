"""Validate vertical-spread money math."""
from options_cli.chains import Chain, Contract
from options_cli.greeks import compute
from options_cli.strategies import build_verticals, build_income


def _c(strike, kind, bid, ask, dte=30):
    g = compute(100, strike, dte / 365, 0.30, is_call=(kind == "call"))
    return Contract("X", "2026-07-01", strike, kind, bid, ask, (bid + ask) / 2,
                    100, 100, 0.30, dte, g)


def _chain(contracts):
    return Chain("X", spot=100.0, rate=0.044, expirations=["2026-07-01"], contracts=contracts)


def test_bull_call_debit_spread_math():
    # buy 100 call @2.00, sell 105 call @0.50 -> debit 1.50, width 5
    ch = _chain([_c(100, "call", 1.9, 2.1), _c(105, "call", 0.4, 0.6)])
    v = build_verticals(ch, "2026-07-01", "call", "bull")[0]
    assert v.debit_credit == "debit"
    assert abs(v.net - 1.5) < 1e-6           # 2.00 - 0.50
    assert abs(v.max_loss - 1.5) < 1e-6
    assert abs(v.max_profit - 3.5) < 1e-6    # width 5 - debit 1.5
    assert abs(v.breakeven - 101.5) < 1e-6   # low strike + debit
    assert 0 < v.pop < 1


def test_bull_put_credit_spread_math():
    # sell 100 put @2.00, buy 95 put @0.50 -> credit 1.50, width 5
    ch = _chain([_c(95, "put", 0.4, 0.6), _c(100, "put", 1.9, 2.1)])
    v = build_verticals(ch, "2026-07-01", "put", "bull")[0]
    assert v.debit_credit == "credit"
    assert abs(v.max_profit - 1.5) < 1e-6    # credit
    assert abs(v.max_loss - 3.5) < 1e-6      # width - credit
    assert abs(v.breakeven - 98.5) < 1e-6    # high strike - credit


def test_cash_secured_put_math():
    # spot 100, sell the 95 put @2.00 -> BE 93, keep premium if S>95
    ch = _chain([_c(95, "put", 1.9, 2.1)])
    t = build_income(ch, "2026-07-01", "put")[0]
    assert t.type == "cash_secured_put"
    assert abs(t.breakeven - 93.0) < 1e-6
    assert abs(t.max_profit - 2.0) < 1e-6
    assert abs(t.capital - 9500) < 1e-6
    assert t.pop > 0.5 and t.theta > 0      # seller: positive theta (decay = income)


def test_covered_call_math():
    # spot 100, sell the 105 call @2.00 -> BE 98, if-called profit = 2 + 5 = 7
    ch = _chain([_c(105, "call", 1.9, 2.1)])
    t = build_income(ch, "2026-07-01", "call")[0]
    assert t.type == "covered_call"
    assert abs(t.breakeven - 98.0) < 1e-6
    assert abs(t.max_profit - 7.0) < 1e-6
    assert t.pop > 0.5
