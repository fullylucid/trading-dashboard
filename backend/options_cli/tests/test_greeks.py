"""Validate Black-Scholes Greeks against hand-computed reference values."""
from options_cli.greeks import compute


def _approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_atm_call_reference():
    # S=100 K=100 T=1 IV=20% r=5% q=0  -> d1=0.35, d2=0.15
    g = compute(100, 100, 1.0, 0.20, rate=0.05, is_call=True)
    assert _approx(g.delta, 0.63683, 1e-3)      # N(0.35)
    assert _approx(g.prob_itm, 0.55962, 1e-3)   # N(0.15)
    assert _approx(g.gamma, 0.018762, 1e-4)
    assert _approx(g.vega, 0.37524, 1e-3)        # per 1 vol point
    assert g.theta < 0                           # long call decays


def test_put_call_delta_relationship():
    c = compute(100, 100, 1.0, 0.20, rate=0.05, is_call=True)
    p = compute(100, 100, 1.0, 0.20, rate=0.05, is_call=False)
    # put delta = call delta - e^{-qT}; q=0 -> call - 1
    assert _approx(p.delta, c.delta - 1.0, 1e-6)
    assert _approx(c.gamma, p.gamma, 1e-9)       # gamma identical
    assert _approx(c.vega, p.vega, 1e-9)


def test_deep_itm_call_delta_near_one():
    g = compute(200, 100, 0.5, 0.30, rate=0.044, is_call=True)
    assert g.delta > 0.95
    assert g.prob_itm > 0.9


def test_degenerate_inputs_safe():
    assert compute(0, 100, 1, 0.2).delta == 0.0
    assert compute(100, 100, 0, 0.2).vega == 0.0
    assert compute(100, 100, 1, 0).gamma == 0.0
