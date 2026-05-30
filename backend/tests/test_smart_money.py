"""PURE tests for ``sector_rotation.smart_money`` per-sector aggregation.

NO network is touched. Every test feeds crafted insider *clusters* (the shape
``analytics.insider.cluster_buys`` produces, plus a ``sector`` tag) and 13F
per-sector market-value snapshots into the deterministic aggregation/fusion
helpers. The IO function ``fetch_sector_insider_clusters`` is intentionally NOT
exercised against the live SEC endpoint.

Run: ``cd backend && pytest tests/test_smart_money.py``
"""

import pytest

from sector_rotation.smart_money import (
    aggregate_clusters_by_sector,
    aggregate_13f_by_sector,
    fuse_smart_money,
)


def _cluster(symbol, sector, insiders, *, total_value=300_000.0, span=("2026-05-01", "2026-05-02"), director=True):
    """Build a sector-tagged cluster like ``cluster_buys`` emits.

    ``insiders`` is a list of distinct insider display names. ``span`` is
    (start_date, end_date). A tight (<=3d) window + director involvement keeps
    the per-issuer ``score_insider_signal`` confidence comfortably > 0.
    """
    insiders = [n.strip().upper() for n in insiders]
    filings = [
        {
            "symbol": symbol,
            "insider": name,
            "transaction_code": "P",
            "transaction_date": span[0],
            "is_director": director,
        }
        for name in insiders
    ]
    return {
        "symbol": symbol,
        "sector": sector,
        "insiders": sorted(insiders),
        "num_insiders": len(insiders),
        "num_buys": len(filings),
        "start_date": span[0],
        "end_date": span[1],
        "total_shares": 1000.0 * len(filings),
        "total_value": total_value,
        "filings": filings,
    }


# --------------------------------------------------------------------------- #
# aggregate_clusters_by_sector
# --------------------------------------------------------------------------- #
def test_empty_input_returns_empty():
    assert aggregate_clusters_by_sector([]) == {}
    assert aggregate_clusters_by_sector(None) == {}


def test_single_cluster_maps_to_its_sector():
    clusters = [_cluster("NVDA", "Information Technology", ["Jensen Huang", "Colette Kress"])]
    out = aggregate_clusters_by_sector(clusters)
    assert set(out) == {"Information Technology"}
    row = out["Information Technology"]
    assert row["etf"] == "XLK"
    assert row["num_clusters"] == 1
    assert row["num_insiders"] == 2
    assert row["symbols"] == ["NVDA"]
    assert row["source"] == "insider_form4"
    assert row["lagging"] is False
    assert row["score"] > 0


def test_multiple_clusters_same_sector_sum_and_dedupe_insiders():
    clusters = [
        _cluster("NVDA", "Information Technology", ["Jensen Huang", "Colette Kress"]),
        # AAPL also Tech; one insider name overlaps to test distinct counting.
        _cluster("AAPL", "Information Technology", ["Tim Cook", "JENSEN HUANG"]),
    ]
    out = aggregate_clusters_by_sector(clusters)
    row = out["Information Technology"]
    assert row["num_clusters"] == 2
    # 3 distinct insiders across the two clusters (Jensen Huang counted once).
    assert row["num_insiders"] == 3
    assert row["symbols"] == ["AAPL", "NVDA"]
    # score is the (capped) sum of two positive cluster confidences.
    assert row["score"] > 0


def test_score_capped_at_100():
    # Many strong clusters in one sector -> summed confidence would exceed 100.
    clusters = [
        _cluster(f"SYM{i}", "Energy", [f"A{i}", f"B{i}", f"C{i}", f"D{i}"], total_value=5_000_000.0)
        for i in range(6)
    ]
    out = aggregate_clusters_by_sector(clusters)
    assert out["Energy"]["score"] == 100.0


def test_clusters_split_across_sectors():
    clusters = [
        _cluster("XOM", "Energy", ["Darren Woods", "Kathryn Mikells"]),
        _cluster("JPM", "Financials", ["Jamie Dimon", "Jeremy Barnum"]),
    ]
    out = aggregate_clusters_by_sector(clusters)
    assert set(out) == {"Energy", "Financials"}
    assert out["Energy"]["etf"] == "XLE"
    assert out["Financials"]["etf"] == "XLF"


def test_vendor_sector_name_normalized():
    # "Technology" / "Financial Services" are yfinance spellings -> canonical.
    clusters = [
        _cluster("MSFT", "Technology", ["Satya Nadella", "Amy Hood"]),
        _cluster("BAC", "Financial Services", ["Brian Moynihan", "Alastair Borthwick"]),
    ]
    out = aggregate_clusters_by_sector(clusters)
    assert "Information Technology" in out
    assert "Financials" in out
    assert out["Information Technology"]["etf"] == "XLK"


def test_unresolvable_sector_dropped():
    clusters = [
        _cluster("XXX", None, ["A One", "B Two"]),
        _cluster("YYY", "Tobacco", ["C Three", "D Four"]),  # not a GICS sector
        _cluster("NVDA", "Information Technology", ["Jensen Huang", "Colette Kress"]),
    ]
    out = aggregate_clusters_by_sector(clusters)
    assert set(out) == {"Information Technology"}


def test_non_cluster_zero_score_excluded():
    # A single-insider "cluster" scores 0 in score_insider_signal -> no weight.
    lone = _cluster("NVDA", "Information Technology", ["Jensen Huang"])
    lone["num_insiders"] = 1
    out = aggregate_clusters_by_sector([lone])
    assert out == {}


def test_total_value_summed():
    clusters = [
        _cluster("XOM", "Energy", ["A One", "B Two"], total_value=100_000.0),
        _cluster("CVX", "Energy", ["C Three", "D Four"], total_value=250_000.0),
    ]
    out = aggregate_clusters_by_sector(clusters)
    assert out["Energy"]["total_value"] == pytest.approx(350_000.0)
    assert out["Energy"]["num_buys"] == 4


# --------------------------------------------------------------------------- #
# aggregate_13f_by_sector  (optional, lagging)
# --------------------------------------------------------------------------- #
def test_13f_marks_everything_lagging():
    out = aggregate_13f_by_sector({"Energy": 1000.0}, {"Energy": 900.0})
    assert out["Energy"]["lagging"] is True
    assert out["Energy"]["source"] == "13f_institutional"


def test_13f_inflow_outflow_flat_direction():
    cur = {"Energy": 1200.0, "Financials": 800.0, "Utilities": 1010.0}
    prior = {"Energy": 1000.0, "Financials": 1000.0, "Utilities": 1000.0}
    out = aggregate_13f_by_sector(cur, prior, min_pct_flag=0.05)
    assert out["Energy"]["direction"] == "inflow"       # +20%
    assert out["Energy"]["net_flow"] == pytest.approx(200.0)
    assert out["Energy"]["pct_change"] == pytest.approx(0.2)
    assert out["Financials"]["direction"] == "outflow"  # -20%
    assert out["Utilities"]["direction"] == "flat"      # +1% < 5% threshold


def test_13f_no_prior_quarter_levels_only():
    out = aggregate_13f_by_sector({"Energy": 1000.0})
    assert out["Energy"]["net_flow"] is None
    assert out["Energy"]["pct_change"] is None
    assert out["Energy"]["direction"] == "flat"
    assert out["Energy"]["mv_current"] == pytest.approx(1000.0)


def test_13f_normalizes_and_drops_unknown_sectors():
    cur = {"Technology": 500.0, "Tobacco": 999.0}  # vendor name + bogus
    out = aggregate_13f_by_sector(cur)
    assert set(out) == {"Information Technology"}


# --------------------------------------------------------------------------- #
# fuse_smart_money
# --------------------------------------------------------------------------- #
def test_fuse_passthrough_without_13f():
    insider = aggregate_clusters_by_sector(
        [_cluster("NVDA", "Information Technology", ["Jensen Huang", "Colette Kress"])]
    )
    fused = fuse_smart_money(insider)
    assert fused["Information Technology"]["score"] == insider["Information Technology"]["score"]
    assert fused["Information Technology"]["lagging"] is False
    assert fused["Information Technology"]["f13f"] is None


def test_fuse_inflow_bonus_outflow_penalty():
    insider = aggregate_clusters_by_sector(
        [
            _cluster("NVDA", "Information Technology", ["Jensen Huang", "Colette Kress"]),
            _cluster("XOM", "Energy", ["Darren Woods", "Kathryn Mikells"]),
        ]
    )
    tech_base = insider["Information Technology"]["score"]
    energy_base = insider["Energy"]["score"]
    f13f = aggregate_13f_by_sector(
        {"Information Technology": 1200.0, "Energy": 800.0},
        {"Information Technology": 1000.0, "Energy": 1000.0},
    )
    fused = fuse_smart_money(insider, f13f, f13f_inflow_bonus=8.0, f13f_outflow_penalty=8.0)
    # Tech got an inflow bonus, Energy got an outflow penalty (clamped >= 0).
    assert fused["Information Technology"]["score"] == pytest.approx(min(100.0, tech_base + 8.0))
    assert fused["Energy"]["score"] == pytest.approx(max(0.0, energy_base - 8.0))
    # insider_score preserved separately.
    assert fused["Information Technology"]["insider_score"] == tech_base


def test_fuse_13f_only_sector_is_muted_and_lagging():
    insider = {}  # no timely insider data
    f13f = aggregate_13f_by_sector({"Energy": 1200.0}, {"Energy": 1000.0})
    fused = fuse_smart_money(insider, f13f, f13f_inflow_bonus=8.0)
    row = fused["Energy"]
    assert row["lagging"] is True
    assert row["insider_score"] == 0.0
    assert row["score"] == pytest.approx(8.0)  # only the inflow bonus
    assert row["insider"] is None


def test_fuse_sorted_by_score_desc():
    insider = aggregate_clusters_by_sector(
        [
            _cluster("XOM", "Energy", ["A One", "B Two"], total_value=10_000.0),
            _cluster(
                "NVDA",
                "Information Technology",
                ["Jensen Huang", "Colette Kress", "Debora Shoquist", "Tim Teter"],
                total_value=5_000_000.0,
            ),
        ]
    )
    fused = fuse_smart_money(insider)
    scores = [v["score"] for v in fused.values()]
    assert scores == sorted(scores, reverse=True)
    # Tech (4 insiders, big $) should outrank Energy (2 insiders, tiny $).
    assert list(fused)[0] == "Information Technology"


def test_fuse_clamps_score_range():
    insider = aggregate_clusters_by_sector(
        [_cluster("NVDA", "Information Technology", ["A", "B"], total_value=100.0)]
    )
    # Force a large outflow penalty -> would go negative -> clamp to 0.
    f13f = aggregate_13f_by_sector(
        {"Information Technology": 1.0}, {"Information Technology": 1000.0}
    )
    fused = fuse_smart_money(insider, f13f, f13f_outflow_penalty=999.0)
    assert fused["Information Technology"]["score"] == 0.0
