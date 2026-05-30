"""PURE tests for ``sector_rotation.catalyst``.

NO network is touched. Every test feeds crafted earnings/econ dicts into the
deterministic scoring helpers. The IO functions (``fetch_earnings_calendar``,
``fetch_fred_latest``, ``fetch_econ_releases``) are intentionally NOT exercised
against live endpoints — we only assert their no-key / empty-degradation paths.

Run: ``~/.config/agent-bridge/testvenv/bin/python -m pytest tests/test_catalyst.py``
"""

import pytest

from sector_rotation.catalyst import (
    ECON_SECTOR_MAP,
    ECON_SERIES,
    aggregate_earnings_by_sector,
    fetch_earnings_calendar,
    fetch_econ_releases,
    fetch_fred_latest,
    map_econ_release_to_sectors,
    market_cap_weight,
    score_catalyst_pressure,
    score_earnings_clustering,
)
from sector_rotation.sectors import SECTOR_TO_ETF


def _ev(symbol, date="2026-05-12", market_cap=None, **extra):
    d = {"symbol": symbol, "date": date, "market_cap": market_cap}
    d.update(extra)
    return d


# --------------------------------------------------------------------------- #
# market_cap_weight
# --------------------------------------------------------------------------- #
def test_market_cap_weight_tiers():
    assert market_cap_weight(2e12) == 3      # >$1T mega
    assert market_cap_weight(1.0e12) == 2    # exactly $1T -> not > $1T -> large
    assert market_cap_weight(5e11) == 2      # $500B large
    assert market_cap_weight(3e11) == 2      # exactly $300B boundary -> large
    assert market_cap_weight(2.99e11) == 1   # just under $300B -> mid/small
    assert market_cap_weight(1e9) == 1       # small


def test_market_cap_weight_missing_is_one_not_zero():
    # Unknown cap must still count as a report (weight 1), never dropped.
    assert market_cap_weight(None) == 1
    assert market_cap_weight("") == 1
    assert market_cap_weight("garbage") == 1


# --------------------------------------------------------------------------- #
# aggregate_earnings_by_sector
# --------------------------------------------------------------------------- #
def test_aggregate_basic_counts_and_weights():
    events = [
        _ev("JPM", market_cap=6e11),    # Financials, large -> w2
        _ev("BAC", market_cap=3e11),    # Financials, large -> w2
        _ev("AAPL", market_cap=3e12),   # Tech, mega -> w3
    ]
    t2s = {
        "JPM": "Financials",
        "BAC": "Financials",
        "AAPL": "Information Technology",
    }
    agg = aggregate_earnings_by_sector(events, t2s)
    assert agg["Financials"]["count"] == 2
    assert agg["Financials"]["weighted_count"] == 4.0  # 2 + 2
    assert agg["Financials"]["symbols"] == ["BAC", "JPM"]
    assert agg["Financials"]["etf"] == "XLF"
    assert agg["Information Technology"]["count"] == 1
    assert agg["Information Technology"]["weighted_count"] == 3.0


def test_aggregate_drops_unmapped_tickers():
    events = [_ev("JPM"), _ev("ZZZZ")]
    agg = aggregate_earnings_by_sector(events, {"JPM": "Financials", "ZZZZ": None})
    assert set(agg) == {"Financials"}
    assert agg["Financials"]["count"] == 1


def test_aggregate_dedupes_same_company():
    # Same company appearing twice (e.g. amended) counts once.
    events = [_ev("JPM"), _ev("JPM")]
    agg = aggregate_earnings_by_sector(events, {"JPM": "Financials"})
    assert agg["Financials"]["count"] == 1
    assert agg["Financials"]["weighted_count"] == 1.0


def test_aggregate_normalizes_vendor_sector_names():
    # ticker_to_sector may carry vendor spellings; they must normalize.
    agg = aggregate_earnings_by_sector(
        [_ev("AAPL")], {"AAPL": "Technology"}
    )
    assert "Information Technology" in agg


def test_aggregate_case_insensitive_tickers():
    agg = aggregate_earnings_by_sector(
        [_ev("jpm")], {"JPM": "Financials"}
    )
    assert agg["Financials"]["count"] == 1


def test_aggregate_empty_inputs():
    assert aggregate_earnings_by_sector([], {}) == {}
    assert aggregate_earnings_by_sector(None, None) == {}


# --------------------------------------------------------------------------- #
# score_earnings_clustering
# --------------------------------------------------------------------------- #
def test_clustering_busiest_sector_scores_100():
    agg = {
        "Financials": {"count": 4, "weighted_count": 8.0, "symbols": [], "etf": "XLF"},
        "Energy": {"count": 1, "weighted_count": 2.0, "symbols": [], "etf": "XLE"},
    }
    scored = score_earnings_clustering(agg)
    assert scored["Financials"]["score"] == 100.0
    assert scored["Energy"]["score"] == 25.0  # 2/8 * 100


def test_clustering_in_season_flag_for_heavy_tail():
    agg = {
        "Financials": {"weighted_count": 10.0, "count": 5, "etf": "XLF"},
        "Energy": {"weighted_count": 2.0, "count": 1, "etf": "XLE"},
        "Utilities": {"weighted_count": 1.0, "count": 1, "etf": "XLU"},
    }
    scored = score_earnings_clustering(agg)
    # Financials is the heavy tail -> in earnings season.
    assert scored["Financials"]["in_earnings_season"] is True
    # The smallest is not.
    assert scored["Utilities"]["in_earnings_season"] is False


def test_clustering_all_sectors_included_with_zero():
    agg = {"Financials": {"weighted_count": 4.0, "count": 2, "etf": "XLF"}}
    scored = score_earnings_clustering(agg, all_sectors=list(SECTOR_TO_ETF))
    assert set(scored) == set(SECTOR_TO_ETF)
    assert scored["Energy"]["score"] == 0.0
    assert scored["Energy"]["in_earnings_season"] is False


def test_clustering_no_events_all_zero_no_flags():
    scored = score_earnings_clustering({}, all_sectors=["Financials", "Energy"])
    assert all(v["score"] == 0.0 for v in scored.values())
    assert all(v["in_earnings_season"] is False for v in scored.values())


def test_clustering_single_sector_not_flagged_in_season():
    # With only one reporting sector there is no "concentration" to flag.
    agg = {"Financials": {"weighted_count": 5.0, "count": 3, "etf": "XLF"}}
    scored = score_earnings_clustering(agg)
    assert scored["Financials"]["score"] == 100.0
    assert scored["Financials"]["in_earnings_season"] is False


# --------------------------------------------------------------------------- #
# map_econ_release_to_sectors
# --------------------------------------------------------------------------- #
def test_econ_map_unknown_series_empty():
    assert map_econ_release_to_sectors({"series_id": "NOPE", "value": 1, "previous": 1}) == {}


def test_econ_map_missing_delta_empty():
    assert map_econ_release_to_sectors({"series_id": "CPIAUCSL", "value": 5}) == {}
    assert map_econ_release_to_sectors({"series_id": "CPIAUCSL", "value": ".", "previous": 5}) == {}


def test_econ_map_hot_cpi_signs():
    # Hot CPI (value > previous): tailwind Financials, headwind Utilities/REITs.
    rel = {"series_id": "CPIAUCSL", "value": 315.0, "previous": 313.0}
    impact = map_econ_release_to_sectors(rel)
    assert impact["Financials"] > 0
    assert impact["Utilities"] < 0
    assert impact["Real Estate"] < 0
    # Signs are mirror images for opposite-sign sectors.
    assert impact["Financials"] == pytest.approx(-impact["Utilities"])


def test_econ_map_cool_cpi_flips_signs():
    rel = {"series_id": "CPIAUCSL", "value": 311.0, "previous": 313.0}
    impact = map_econ_release_to_sectors(rel)
    # Cooling inflation: now a headwind for Financials, tailwind for Utilities.
    assert impact["Financials"] < 0
    assert impact["Utilities"] > 0


def test_econ_map_level_series_uses_absolute_change():
    # 10Y up 0.5% (absolute) -> Financials tailwind, Utilities/REITs headwind.
    rel = {"series_id": "DGS10", "value": 4.5, "previous": 4.0}
    impact = map_econ_release_to_sectors(rel)
    assert impact["Financials"] == pytest.approx(15.0)  # 0.5 * 30 * (+1)
    assert impact["Utilities"] == pytest.approx(-15.0)


def test_econ_map_clamped():
    # A massive move must be clamped to +/- clamp.
    rel = {"series_id": "DGS10", "value": 10.0, "previous": 1.0}
    impact = map_econ_release_to_sectors(rel, clamp=30.0)
    assert impact["Financials"] == 30.0
    assert impact["Utilities"] == -30.0


def test_econ_map_zero_previous_pct_series_empty():
    # Percent-basis series with previous==0 cannot compute a surprise.
    assert map_econ_release_to_sectors({"series_id": "CPIAUCSL", "value": 5, "previous": 0}) == {}


def test_econ_map_sectors_are_canonical():
    for series_id, mapping in ECON_SECTOR_MAP.items():
        for sector in mapping:
            assert sector in SECTOR_TO_ETF, f"{series_id}: {sector!r} not canonical"


# --------------------------------------------------------------------------- #
# score_catalyst_pressure
# --------------------------------------------------------------------------- #
def test_catalyst_empty_inputs():
    assert score_catalyst_pressure() == {}
    assert score_catalyst_pressure({}, []) == {}


def test_catalyst_earnings_only_centered():
    earn = {
        "Financials": {"score": 100.0, "in_earnings_season": True, "etf": "XLF"},
        "Energy": {"score": 0.0, "in_earnings_season": False, "etf": "XLE"},
    }
    out = score_catalyst_pressure(earn, [], earnings_weight=0.6, econ_weight=0.4)
    # score 100 -> 0..50 tailwind +50 -> *0.6 = +30
    assert out["Financials"]["catalyst_score"] == pytest.approx(30.0)
    # score 0 -> 0 tailwind -> 0 (no reporting is NEUTRAL, never a penalty)
    assert out["Energy"]["catalyst_score"] == pytest.approx(0.0)
    assert out["Financials"]["in_earnings_season"] is True
    assert out["Financials"]["etf"] == "XLF"


def test_catalyst_econ_only():
    releases = [{"series_id": "DGS10", "value": 4.5, "previous": 4.0}]  # +15 Fin, -15 Util/RE
    out = score_catalyst_pressure({}, releases, earnings_weight=0.6, econ_weight=0.4)
    # econ-only: catalyst = 0.4 * econ_impact
    assert out["Financials"]["econ_impact"] == pytest.approx(15.0)
    assert out["Financials"]["catalyst_score"] == pytest.approx(0.4 * 15.0)
    assert out["Utilities"]["catalyst_score"] == pytest.approx(0.4 * -15.0)


def test_catalyst_combines_earnings_and_econ():
    earn = {"Financials": {"score": 100.0, "in_earnings_season": True, "etf": "XLF"}}
    releases = [{"series_id": "DGS10", "value": 4.5, "previous": 4.0}]  # +15 Financials
    out = score_catalyst_pressure(earn, releases, earnings_weight=0.6, econ_weight=0.4)
    # 0.6*(100*0.5) + 0.4*15 = 30 + 6 = 36
    assert out["Financials"]["catalyst_score"] == pytest.approx(36.0)
    # pressure is direction-agnostic magnitude
    assert out["Financials"]["pressure"] > 0


def test_catalyst_econ_summed_across_releases():
    releases = [
        {"series_id": "DGS10", "value": 4.5, "previous": 4.0},     # +15 Financials
        {"series_id": "FEDFUNDS", "value": 5.5, "previous": 5.0},  # +15 Financials
    ]
    out = score_catalyst_pressure({}, releases)
    assert out["Financials"]["econ_impact"] == pytest.approx(30.0)


def test_catalyst_econ_impact_clamped_into_score():
    # Several big releases summing > 50 get clamped at 50 inside the blend.
    releases = [
        {"series_id": "DGS10", "value": 6.0, "previous": 4.0},     # clamps to +30
        {"series_id": "FEDFUNDS", "value": 7.0, "previous": 5.0},  # clamps to +30
    ]
    out = score_catalyst_pressure({}, releases, earnings_weight=0.0, econ_weight=1.0)
    # econ_impact summed = 60, but clamped to 50 for the blended score.
    assert out["Financials"]["econ_impact"] == pytest.approx(60.0)
    assert out["Financials"]["catalyst_score"] == pytest.approx(50.0)


# --------------------------------------------------------------------------- #
# IO degradation paths (no network; just the no-key / empty contracts)
# --------------------------------------------------------------------------- #
def test_fetch_earnings_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert fetch_earnings_calendar() == []


def test_fetch_fred_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fetch_fred_latest("CPIAUCSL") is None


def test_fetch_econ_releases_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fetch_econ_releases() == []


def test_fetch_fred_blank_series_none():
    assert fetch_fred_latest("") is None


# --------------------------------------------------------------------------- #
# Constants sanity
# --------------------------------------------------------------------------- #
def test_econ_series_keys_have_mappings():
    # Every tracked series should have a sector map (and vice versa).
    assert set(ECON_SERIES) == set(ECON_SECTOR_MAP)
