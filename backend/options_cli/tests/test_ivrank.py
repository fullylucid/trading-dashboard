"""IV-rank: math correctness on hand-checkable series, cold-start honesty,
no-look-ahead, and store idempotency. No network — chains are built in-memory."""
import datetime as dt

import pytest

from options_cli.chains import Chain, Contract
from options_cli.greeks import Greeks
from options_cli.ivrank import (
    IVHistoryStore, atm_iv, compute_metrics, iv_percentile, iv_rank,
)

EXP = "2026-07-10"


def _contract(strike: float, kind: str, iv: float) -> Contract:
    return Contract(symbol="TEST", expiration=EXP, strike=strike, kind=kind,
                    bid=1.0, ask=1.2, last=1.1, volume=10, open_interest=100,
                    iv=iv, dte=30, greeks=Greeks(0, 0, 0, 0, 0, 0))


def _chain(spot: float, contracts) -> Chain:
    return Chain("TEST", spot, 0.044, [EXP], list(contracts))


# --------------------------------------------------------------------------- #
# ATM IV extraction
# --------------------------------------------------------------------------- #
def test_atm_iv_averages_call_and_put_at_nearest_strike():
    ch = _chain(100.0, [
        _contract(95, "call", 0.30), _contract(100, "call", 0.20), _contract(105, "call", 0.28),
        _contract(95, "put", 0.32), _contract(100, "put", 0.24), _contract(105, "put", 0.30),
    ])
    assert atm_iv(ch, EXP) == 0.22  # (0.20 + 0.24) / 2 at the 100 strike


def test_atm_iv_skips_garbage_iv_and_uses_one_side_if_needed():
    # 100-strike call has a dead-quote IV (~1e-5); nearest valid call is the 105.
    # Puts are all garbage -> call side only.
    ch = _chain(100.0, [
        _contract(100, "call", 1e-05), _contract(105, "call", 0.26),
        _contract(100, "put", 1e-05),
    ])
    assert atm_iv(ch, EXP) == 0.26


def test_atm_iv_none_when_nothing_usable():
    ch = _chain(100.0, [_contract(100, "call", 1e-05)])
    assert atm_iv(ch, EXP) is None
    assert atm_iv(_chain(0.0, [_contract(100, "call", 0.2)]), EXP) is None  # no spot


# --------------------------------------------------------------------------- #
# Rank / percentile math (hand-checked)
# --------------------------------------------------------------------------- #
def test_rank_and_percentile_hand_checked():
    past = [0.10, 0.15, 0.20, 0.25, 0.30]
    # rank: (0.20 - 0.10) / (0.30 - 0.10) = 0.5  (approx: raw fn doesn't round)
    assert iv_rank(past, 0.20) == pytest.approx(0.5)
    # percentile: 3 of 5 days had IV <= 0.20
    assert iv_percentile(past, 0.20) == 0.6


def test_rank_clamps_outside_observed_range():
    past = [0.10, 0.30]
    assert iv_rank(past, 0.50) == 1.0
    assert iv_rank(past, 0.05) == 0.0


def test_rank_undefined_on_flat_or_empty_series():
    assert iv_rank([0.2, 0.2, 0.2], 0.2) is None  # flat: rank undefined, not 0 or 1
    assert iv_rank([], 0.2) is None
    assert iv_percentile([], 0.2) is None


def test_compute_metrics_sufficient_path():
    past = [0.10, 0.15, 0.20, 0.25, 0.30]
    m = compute_metrics(past, 0.20, window=252, min_obs=5)
    assert m["sufficient"] is True
    assert m["iv_rank"] == 0.5
    assert m["iv_percentile"] == 0.6
    assert m["n_days"] == 5


def test_compute_metrics_cold_start_returns_no_garbage_rank():
    m = compute_metrics([0.1, 0.2], 0.15, min_obs=60)
    assert m["sufficient"] is False
    assert m["iv_rank"] is None
    assert m["iv_percentile"] is None
    assert m["reason"] == "insufficient_history"
    assert m["n_days"] == 2


def test_compute_metrics_windows_to_trailing_observations():
    # 300 obs: first 48 are extreme highs; window=252 must drop them so the
    # rank reflects only the trailing year.
    past = [0.90] * 48 + [0.10 + 0.0005 * i for i in range(252)]
    m = compute_metrics(past, 0.10, window=252, min_obs=60)
    assert m["n_days"] == 252
    assert m["iv_rank"] == 0.0  # at the min of the trailing window despite old 0.90s


# --------------------------------------------------------------------------- #
# Store: idempotency, weekend guard, no-look-ahead
# --------------------------------------------------------------------------- #
def test_store_idempotent_by_date(tmp_path):
    store = IVHistoryStore(path=str(tmp_path / "iv.json"))
    day = dt.date(2026, 6, 11)  # a Thursday
    assert store.record("SPY", day, 0.18, spot=600.0, expiration=EXP, dte=29)
    assert store.record("SPY", day, 0.19)  # same-day re-run overwrites
    rows = store.series("SPY")
    assert len(rows) == 1
    assert rows[0]["iv"] == 0.19
    assert rows[0]["date"] == "2026-06-11"


def test_store_rejects_weekends_and_invalid_iv(tmp_path):
    store = IVHistoryStore(path=str(tmp_path / "iv.json"))
    assert not store.record("SPY", dt.date(2026, 6, 13), 0.18)   # Saturday
    assert not store.record("SPY", dt.date(2026, 6, 14), 0.18)   # Sunday
    assert not store.record("SPY", dt.date(2026, 6, 11), 0.0)    # dead-quote IV
    assert not store.record("SPY", dt.date(2026, 6, 11), float("nan"))
    assert store.series("SPY") == []


def test_no_look_ahead(tmp_path):
    """Metrics computed as-of day T must not change when later days arrive."""
    store = IVHistoryStore(path=str(tmp_path / "iv.json"))
    # Mon Jun 1 .. Thu Jun 4 2026, rising IV
    for i, iv in enumerate([0.10, 0.20, 0.30, 0.40]):
        assert store.record("SPY", dt.date(2026, 6, 1) + dt.timedelta(days=i), iv)

    as_of = dt.date(2026, 6, 3)
    past = [r["iv"] for r in store.series("SPY", before=as_of)]
    assert past == [0.10, 0.20]  # strictly before Jun 3: its own and later days excluded
    before = compute_metrics(past, 0.15, min_obs=2)

    # A "future" day lands in the store; the as-of view must be identical.
    assert store.record("SPY", dt.date(2026, 6, 5), 0.99)
    past_again = [r["iv"] for r in store.series("SPY", before=as_of)]
    assert past_again == past
    assert compute_metrics(past_again, 0.15, min_obs=2) == before


def test_store_tolerates_missing_and_corrupt_files(tmp_path):
    missing = IVHistoryStore(path=str(tmp_path / "nope.json"))
    assert missing.series("SPY") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    corrupt = IVHistoryStore(path=str(bad))
    assert corrupt.series("SPY") == []
    assert corrupt.record("SPY", dt.date(2026, 6, 11), 0.18)  # recovers by rewriting
    assert corrupt.series("SPY")[0]["iv"] == 0.18
