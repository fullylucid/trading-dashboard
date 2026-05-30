"""PURE tests for the SPDR sector-ETF <-> GICS universe (``sector_rotation.sectors``).

No network. These exercise only the constant maps and pure helpers; the IO
function :func:`sector_for_ticker` is covered (only on its no-network fast path)
to confirm a known ETF resolves without touching the network.
"""

import pytest

from sector_rotation.sectors import (
    ALL_ROTATION_SYMBOLS,
    BENCHMARK,
    ETF_TO_SECTOR,
    SECTOR_ETFS,
    SECTOR_ETF_SYMBOLS,
    SECTOR_TO_ETF,
    etf_to_sector,
    is_sector_etf,
    normalize_sector_name,
    sector_for_ticker,
    sector_to_etf,
)

# The canonical 11 SPDR sector ETFs.
EXPECTED_ETFS = {
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLY",
    "XLP",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
}


# --------------------------------------------------------------------------- #
# Universe completeness
# --------------------------------------------------------------------------- #

def test_exactly_eleven_sector_etfs():
    assert len(SECTOR_ETFS) == 11
    assert set(SECTOR_ETFS) == EXPECTED_ETFS


def test_all_eleven_etfs_present():
    for etf in EXPECTED_ETFS:
        assert etf in SECTOR_ETFS, f"missing sector ETF {etf}"


def test_eleven_distinct_sectors():
    sectors = set(SECTOR_ETFS.values())
    assert len(sectors) == 11  # no two ETFs share a GICS sector


def test_benchmark_is_spy_and_not_a_sector():
    assert BENCHMARK == "SPY"
    assert "SPY" not in SECTOR_ETFS


def test_specific_etf_sector_pairs():
    # Spot-check the trickier / commonly-confused ones.
    assert SECTOR_ETFS["XLK"] == "Information Technology"
    assert SECTOR_ETFS["XLF"] == "Financials"
    assert SECTOR_ETFS["XLV"] == "Health Care"
    assert SECTOR_ETFS["XLY"] == "Consumer Discretionary"
    assert SECTOR_ETFS["XLP"] == "Consumer Staples"
    assert SECTOR_ETFS["XLRE"] == "Real Estate"
    assert SECTOR_ETFS["XLC"] == "Communication Services"


# --------------------------------------------------------------------------- #
# Map round-trips & consistency
# --------------------------------------------------------------------------- #

def test_etf_to_sector_alias_matches_source():
    assert ETF_TO_SECTOR == SECTOR_ETFS
    assert ETF_TO_SECTOR is not SECTOR_ETFS  # defensive copy, not the same object


def test_reverse_map_round_trip_etf_sector_etf():
    for etf, sector in SECTOR_ETFS.items():
        assert SECTOR_TO_ETF[sector] == etf


def test_reverse_map_round_trip_sector_etf_sector():
    for sector, etf in SECTOR_TO_ETF.items():
        assert SECTOR_ETFS[etf] == sector


def test_reverse_map_is_bijection():
    assert len(SECTOR_TO_ETF) == len(SECTOR_ETFS) == 11
    assert set(SECTOR_TO_ETF.values()) == EXPECTED_ETFS


def test_symbol_tuple_and_all_symbols():
    assert set(SECTOR_ETF_SYMBOLS) == EXPECTED_ETFS
    assert len(SECTOR_ETF_SYMBOLS) == 11
    assert set(ALL_ROTATION_SYMBOLS) == EXPECTED_ETFS | {"SPY"}
    assert len(ALL_ROTATION_SYMBOLS) == 12


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def test_etf_to_sector_helper_round_trip():
    for etf, sector in SECTOR_ETFS.items():
        assert etf_to_sector(etf) == sector
        assert etf_to_sector(etf.lower()) == sector  # case-insensitive


def test_etf_to_sector_helper_unknown():
    assert etf_to_sector("AAPL") is None
    assert etf_to_sector("SPY") is None
    assert etf_to_sector("") is None
    assert etf_to_sector(None) is None


def test_sector_to_etf_helper_round_trip():
    for sector, etf in SECTOR_TO_ETF.items():
        assert sector_to_etf(sector) == etf


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("Technology", "XLK"),
        ("Financial Services", "XLF"),
        ("Healthcare", "XLV"),
        ("Consumer Cyclical", "XLY"),
        ("Consumer Defensive", "XLP"),
        ("Basic Materials", "XLB"),
        ("Real Estate", "XLRE"),
        ("Communication Services", "XLC"),
    ],
)
def test_sector_to_etf_accepts_vendor_variants(variant, expected):
    assert sector_to_etf(variant) == expected


def test_sector_to_etf_unknown():
    assert sector_to_etf("Tobacco") is None
    assert sector_to_etf("") is None
    assert sector_to_etf(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Technology", "Information Technology"),
        ("information technology", "Information Technology"),
        ("Financial Services", "Financials"),
        ("Healthcare", "Health Care"),
        ("Health Care", "Health Care"),
        ("  consumer cyclical ", "Consumer Discretionary"),
        ("Consumer Defensive", "Consumer Staples"),
        ("Basic Materials", "Materials"),
        ("REAL ESTATE", "Real Estate"),
        ("Communication Services", "Communication Services"),
    ],
)
def test_normalize_sector_name_variants(raw, expected):
    assert normalize_sector_name(raw) == expected


def test_normalize_sector_name_canonical_passthrough():
    for sector in SECTOR_TO_ETF:
        assert normalize_sector_name(sector) == sector


def test_normalize_sector_name_unknown_and_empty():
    assert normalize_sector_name("Tobacco") is None
    assert normalize_sector_name("") is None
    assert normalize_sector_name(None) is None
    assert normalize_sector_name("   ") is None


def test_normalized_names_all_map_to_an_etf():
    # Every canonical name normalize can emit must be a SECTOR_TO_ETF key.
    for canonical in set(SECTOR_TO_ETF):
        assert sector_to_etf(canonical) is not None


def test_is_sector_etf():
    assert is_sector_etf("XLK") is True
    assert is_sector_etf("xlre") is True
    assert is_sector_etf("SPY") is False
    assert is_sector_etf("AAPL") is False
    assert is_sector_etf("") is False
    assert is_sector_etf(None) is False


# --------------------------------------------------------------------------- #
# IO function: no-network fast path only (does not hit the network)
# --------------------------------------------------------------------------- #

def test_sector_for_ticker_etf_fast_path_no_network():
    # A known SPDR ETF must resolve from the pure map without any network call.
    assert sector_for_ticker("XLK") == "Information Technology"
    assert sector_for_ticker("xlre") == "Real Estate"


def test_sector_for_ticker_empty_returns_none():
    assert sector_for_ticker("") is None
