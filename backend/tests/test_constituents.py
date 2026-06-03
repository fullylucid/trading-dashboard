"""PURE tests for per-constituent contribution (``sector_rotation.constituents``).

No network. Exercises the curated universe + the pure scoring/ranking helpers;
the IO functions (quotes/news) are covered only on their no-key/no-data fast
paths to confirm they degrade to None without touching the network.
"""

import pytest

from sector_rotation.constituents import (
    SECTOR_CONSTITUENTS,
    contribution_of,
    fetch_quote_pct,
    normalize_weights,
    rank_contributors,
    summarize_sector,
)
from sector_rotation.sectors import SECTOR_ETF_SYMBOLS


def test_every_sector_etf_has_constituents():
    # All 11 SPDR sector ETFs must be covered, each with at least a few names.
    for etf in SECTOR_ETF_SYMBOLS:
        assert etf in SECTOR_CONSTITUENTS, f"missing constituents for {etf}"
        assert len(SECTOR_CONSTITUENTS[etf]) >= 5


def test_constituent_symbols_are_clean_and_weighted():
    for etf, members in SECTOR_CONSTITUENTS.items():
        for sym, w in members:
            assert sym == sym.strip().upper() and sym, f"bad symbol in {etf}: {sym!r}"
            assert isinstance(w, (int, float)) and w > 0, f"bad weight in {etf}: {sym}={w}"


def test_normalize_weights_sums_to_one():
    out = normalize_weights([("A", 3.0), ("B", 1.0)])
    assert out == [("A", 0.75), ("B", 0.25)]
    assert abs(sum(w for _, w in out) - 1.0) < 1e-9


def test_normalize_weights_drops_bad_and_handles_empty():
    out = normalize_weights([("A", 2.0), ("B", -1.0), ("C", 0.0), ("D", 2.0)])
    assert dict(out) == {"A": 0.5, "D": 0.5}
    assert normalize_weights([]) == []
    assert normalize_weights([("A", 0.0)]) == []  # all-zero -> empty, no div0


def test_normalize_weights_uppercases_symbols():
    assert normalize_weights([("brk.b", 1.0)]) == [("BRK.B", 1.0)]


def test_contribution_of():
    assert contribution_of(0.15, 4.0) == pytest.approx(0.6)
    assert contribution_of(0.5, -2.0) == pytest.approx(-1.0)
    assert contribution_of(0.15, None) is None  # unknown move != flat
    assert contribution_of("x", 1.0) is None


def test_rank_contributors_splits_and_caps():
    rows = [
        {"symbol": "A", "contribution": 0.6},
        {"symbol": "B", "contribution": -0.3},
        {"symbol": "C", "contribution": 0.9},
        {"symbol": "D", "contribution": -0.8},
        {"symbol": "E", "contribution": None},  # ignored
    ]
    up, down = rank_contributors(rows, top_n=1)
    assert [r["symbol"] for r in up] == ["C"]      # most positive first
    assert [r["symbol"] for r in down] == ["D"]    # most negative first


def test_rank_contributors_returns_copies():
    rows = [{"symbol": "A", "contribution": 1.0}]
    up, _ = rank_contributors(rows)
    up[0]["symbol"] = "MUT"
    assert rows[0]["symbol"] == "A"  # original untouched


def test_summarize_sector_shapes():
    rows = [
        {"symbol": "X", "pct_change": 2.0, "contribution": 0.6},
        {"symbol": "Y", "pct_change": -1.0, "contribution": -0.3},
        {"symbol": "Z", "pct_change": None, "contribution": None},
    ]
    s = summarize_sector("XLK", rows, top_n=5)
    assert s["etf"] == "XLK"
    assert s["sector"] == "Information Technology"
    assert s["n_up"] == 1 and s["n_down"] == 1
    assert s["n_tracked"] == 3
    assert s["breadth"] == pytest.approx(0.5)  # 1 up of 2 with quotes
    assert s["net_contribution"] == pytest.approx(0.3)
    assert [r["symbol"] for r in s["leaders_up"]] == ["X"]
    assert [r["symbol"] for r in s["leaders_down"]] == ["Y"]


def test_summarize_sector_all_unknown_breadth_none():
    rows = [{"symbol": "X", "pct_change": None, "contribution": None}]
    s = summarize_sector("XLF", rows)
    assert s["breadth"] is None
    assert s["n_up"] == 0 and s["n_down"] == 0


def test_fetch_quote_pct_no_key_returns_none():
    # No network: empty key short-circuits before any request.
    assert fetch_quote_pct("AAPL", api_key="") is None
    assert fetch_quote_pct("", api_key="abc") is None
