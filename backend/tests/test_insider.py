"""Unit tests for the PURE helpers in ``analytics/insider.py``.

NO network is touched here — every test feeds crafted filing dicts into the
deterministic helpers (``filter_open_market_buys``, ``cluster_buys``,
``score_insider_signal``). The IO function ``fetch_form4`` is intentionally
NOT exercised against the live SEC endpoint.

Run: ``cd backend && pytest tests/test_insider.py``
"""

import pytest

from analytics.insider import (
    filter_open_market_buys,
    cluster_buys,
    score_insider_signal,
    OPEN_MARKET_BUY_CODE,
)


def _f(symbol, insider, code, txn_date, shares=1000, price=50.0, **extra):
    """Build a filing dict with sensible defaults for tests."""
    d = {
        "symbol": symbol,
        "insider": insider,
        "transaction_code": code,
        "transaction_date": txn_date,
        "shares": shares,
        "price": price,
        "value": shares * price,
    }
    d.update(extra)
    return d


# --------------------------------------------------------------------------- #
# filter_open_market_buys — keep ONLY code 'P'
# --------------------------------------------------------------------------- #
def test_constant_is_p():
    assert OPEN_MARKET_BUY_CODE == "P"


def test_filter_keeps_only_open_market_purchases():
    filings = [
        _f("SMCI", "Liang Charles", "P", "2026-05-01"),   # keep: open-market buy
        _f("SMCI", "Hsu Sara", "A", "2026-05-01"),         # drop: grant/award
        _f("SMCI", "Doe Jane", "M", "2026-05-02"),         # drop: option exercise
        _f("SMCI", "Roe Rick", "S", "2026-05-02"),         # drop: SELL
        _f("SMCI", "Foo Bar", "F", "2026-05-03"),          # drop: tax withholding
        _f("SMCI", "Gee Whiz", "G", "2026-05-03"),         # drop: gift
        _f("SMCI", "Liang Charles", "p", "2026-05-04"),    # keep: lowercase normalised
    ]
    kept = filter_open_market_buys(filings)
    assert len(kept) == 2
    assert all(f["transaction_code"].upper() == "P" for f in kept)
    # input not mutated
    assert len(filings) == 7


def test_filter_empty_and_missing_code():
    assert filter_open_market_buys([]) == []
    # filing with no code field is dropped (treated as non-buy)
    assert filter_open_market_buys([{"symbol": "X", "insider": "A"}]) == []


def test_filter_tolerates_alt_code_key():
    # parser variant uses 'code' instead of 'transaction_code'
    filings = [{"symbol": "X", "insider": "A", "code": "P", "transaction_date": "2026-05-01"}]
    assert len(filter_open_market_buys(filings)) == 1


def test_filter_drops_grant_and_exercise_specifically():
    # 'A' (RSU grant) and 'M' (option exercise) are the two codes most often
    # mistaken for "acquisitions" by naive parsers. Pin that they are dropped.
    filings = [
        _f("X", "A", "A", "2026-05-01"),  # grant/award
        _f("X", "B", "M", "2026-05-01"),  # option exercise
        _f("X", "C", "P", "2026-05-01"),  # the only real buy
    ]
    kept = filter_open_market_buys(filings)
    assert [f["transaction_code"] for f in kept] == ["P"]


# --------------------------------------------------------------------------- #
# cluster_buys — >=2 DISTINCT insiders within the window
# --------------------------------------------------------------------------- #
def test_two_insider_cluster_detected():
    filings = [
        _f("SMCI", "Liang Charles", "P", "2026-05-01", shares=2000, price=40.0),
        _f("SMCI", "Hsu Sara", "P", "2026-05-05", shares=1000, price=42.0),
    ]
    clusters = cluster_buys(filings, window_days=7, min_insiders=2)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["symbol"] == "SMCI"
    assert c["num_insiders"] == 2
    assert sorted(c["insiders"]) == ["HSU SARA", "LIANG CHARLES"]
    assert c["num_buys"] == 2
    assert c["start_date"] == "2026-05-01"
    assert c["end_date"] == "2026-05-05"
    assert c["total_shares"] == 3000.0
    assert c["total_value"] == 2000 * 40.0 + 1000 * 42.0


def test_single_insider_is_not_a_cluster():
    # Same insider buying twice -> only ONE distinct insider -> rejected.
    filings = [
        _f("SMCI", "Liang Charles", "P", "2026-05-01"),
        _f("SMCI", "Liang Charles", "P", "2026-05-03"),
    ]
    assert cluster_buys(filings, window_days=7, min_insiders=2) == []


def test_sells_ignored_in_clustering():
    # Two distinct insiders but one is a SELL -> not >=2 distinct BUYERS.
    filings = [
        _f("SMCI", "Liang Charles", "P", "2026-05-01"),
        _f("SMCI", "Hsu Sara", "S", "2026-05-02"),  # sell -> filtered out
    ]
    assert cluster_buys(filings, window_days=7, min_insiders=2) == []


def test_buys_outside_window_do_not_cluster():
    # Two distinct insiders but 10 days apart with a 7-day window -> no cluster.
    filings = [
        _f("SMCI", "Liang Charles", "P", "2026-05-01"),
        _f("SMCI", "Hsu Sara", "P", "2026-05-11"),
    ]
    assert cluster_buys(filings, window_days=7, min_insiders=2) == []


def test_clusters_are_per_symbol():
    # One insider each on two different symbols -> neither clusters.
    filings = [
        _f("AAA", "Insider One", "P", "2026-05-01"),
        _f("BBB", "Insider Two", "P", "2026-05-02"),
    ]
    assert cluster_buys(filings, window_days=7, min_insiders=2) == []


def test_window_does_not_chain_across_gaps():
    # Anti-look-ahead / anti-transitive-window guard: a third buy outside the
    # FIRST anchor's window must NOT be pulled in just because it is within
    # window_days of the second buy. A@1,B@5,C@10 with window=7 => exactly one
    # cluster {A,B} spanning 05-01..05-05; C@10 is left alone (no cluster).
    # A naive "expand end as we go" implementation would wrongly chain to C.
    filings = [
        _f("Z", "Alice", "P", "2026-05-01"),
        _f("Z", "Bob", "P", "2026-05-05"),
        _f("Z", "Carol", "P", "2026-05-10"),
    ]
    clusters = cluster_buys(filings, window_days=7, min_insiders=2)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["insiders"] == ["ALICE", "BOB"]
    assert c["start_date"] == "2026-05-01"
    assert c["end_date"] == "2026-05-05"


def test_window_boundary_is_inclusive():
    # Exactly window_days apart must cluster; one day more must not.
    inside = [
        _f("Z", "A", "P", "2026-05-01"),
        _f("Z", "B", "P", "2026-05-08"),  # +7 days, inclusive => cluster
    ]
    outside = [
        _f("Z", "A", "P", "2026-05-01"),
        _f("Z", "B", "P", "2026-05-09"),  # +8 days => no cluster
    ]
    assert len(cluster_buys(inside, window_days=7, min_insiders=2)) == 1
    assert cluster_buys(outside, window_days=7, min_insiders=2) == []


def test_grant_and_exercise_dropped_inside_clustering():
    # Two DISTINCT insiders, but one transacts via 'A' (grant) and one via 'M'
    # (exercise) plus one real 'P' buyer. Only one real buyer => NOT a cluster.
    filings = [
        _f("Z", "Alice", "A", "2026-05-01"),  # grant, not a buy
        _f("Z", "Bob", "M", "2026-05-02"),    # exercise, not a buy
        _f("Z", "Carol", "P", "2026-05-02"),  # the only genuine buy
    ]
    assert cluster_buys(filings, window_days=7, min_insiders=2) == []


def test_anonymous_owner_does_not_count_as_distinct():
    # A blank insider name must not be counted toward distinctness, otherwise a
    # single named buyer + an unnamed row would falsely look like a 2-insider
    # cluster.
    filings = [
        _f("Z", "Liang Charles", "P", "2026-05-01"),
        _f("Z", "", "P", "2026-05-02"),  # unnamed owner
    ]
    assert cluster_buys(filings, window_days=7, min_insiders=2) == []


def test_three_insider_cluster_counts_distinct():
    filings = [
        _f("GFS", "Alice", "P", "2026-05-01"),
        _f("GFS", "Bob", "P", "2026-05-02"),
        _f("GFS", "Carol", "P", "2026-05-03"),
        _f("GFS", "Bob", "P", "2026-05-03"),  # dup insider, same window
    ]
    clusters = cluster_buys(filings, window_days=7, min_insiders=2)
    assert len(clusters) == 1
    assert clusters[0]["num_insiders"] == 3
    assert clusters[0]["num_buys"] == 4


# --------------------------------------------------------------------------- #
# score_insider_signal — confidence + bucket
# --------------------------------------------------------------------------- #
def test_score_non_cluster_is_low():
    out = score_insider_signal({"num_insiders": 1, "total_value": 999999})
    assert out["confidence"] == 0.0
    assert out["bucket"] == "low"


def test_score_basic_cluster_exact_low():
    # 2 insiders, $60k (+6), 4-day span (>3 so no tightness), no role.
    # base 40 + 0 extra + 6 + 0 + 0 = 46 -> exactly "low". Pin the number so a
    # weighting regression is caught (the old test accepted low OR watch).
    cluster = {
        "num_insiders": 2,
        "total_value": 60_000,
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
        "filings": [],
    }
    out = score_insider_signal(cluster)
    assert out["confidence"] == 46.0
    assert out["bucket"] == "low"


def test_score_watch_band_threshold():
    # Pin the 60 boundary (nothing else exercises the watch band).
    # 2 insiders (+0), $300k (+12), 9-day span (no tightness), director (+8):
    # 40 + 12 + 8 = 60 -> exactly "watch".
    cluster = {
        "num_insiders": 2,
        "total_value": 300_000,
        "start_date": "2026-05-01",
        "end_date": "2026-05-10",
        "filings": [{"is_director": True}],
    }
    out = score_insider_signal(cluster)
    assert out["confidence"] == 60.0
    assert out["bucket"] == "watch"


def test_score_just_below_watch_is_low():
    # 59 must NOT be promoted to watch (strict >= 60 boundary).
    # 2 insiders, $300k (+12), 9d span (no tightness), no role: 40 + 12 = 52 low;
    # bump to 3 insiders to land just under: 40 + 12(extra) + 6($50k) = 58 -> low.
    cluster = {
        "num_insiders": 3,
        "total_value": 60_000,
        "start_date": "2026-05-01",
        "end_date": "2026-05-10",
        "filings": [],
    }
    out = score_insider_signal(cluster)
    assert out["confidence"] == 58.0
    assert out["bucket"] == "low"


def test_score_strong_cluster_is_high():
    # 4 insiders (+24), >$1M (+18), tight 2d window (+10), director (+8) on top of 40.
    cluster = {
        "num_insiders": 4,
        "total_value": 1_500_000,
        "start_date": "2026-05-01",
        "end_date": "2026-05-03",
        "filings": [{"is_director": True}],
    }
    out = score_insider_signal(cluster)
    assert out["confidence"] >= 80
    assert out["bucket"] == "high"


def test_score_is_clamped_to_100():
    cluster = {
        "num_insiders": 20,
        "total_value": 50_000_000,
        "start_date": "2026-05-01",
        "end_date": "2026-05-01",
        "filings": [{"is_officer": True, "officer_title": "CEO"}],
    }
    out = score_insider_signal(cluster)
    assert out["confidence"] == 100.0
    assert out["bucket"] == "high"


def test_score_end_to_end_from_cluster_buys():
    # Detect a real cluster then score it, exercising the full pure pipeline.
    filings = [
        _f("SMCI", "Alice", "P", "2026-05-01", shares=5000, price=120.0,
           is_director=True),
        _f("SMCI", "Bob", "P", "2026-05-02", shares=4000, price=121.0),
        _f("SMCI", "Carol", "P", "2026-05-02", shares=3000, price=122.0),
        _f("SMCI", "Dave", "S", "2026-05-02"),  # sell ignored
    ]
    clusters = cluster_buys(filings, window_days=7, min_insiders=2)
    assert len(clusters) == 1
    out = score_insider_signal(clusters[0])
    assert out["confidence"] >= 80  # 3 buyers, >$1M, tight, director
    assert out["bucket"] == "high"
    assert "insider buy cluster" in out["reason"]
