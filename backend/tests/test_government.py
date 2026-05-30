"""PURE tests for the GOVERNMENT angle (``sector_rotation.government``).

No network. These exercise only the PURE NAICS->GICS map, the record
normalizers, and the per-sector aggregators — with an **injected** sector
lookup so nothing touches yfinance/Finnhub. The IO fetchers
(:func:`fetch_congressional_trades`, :func:`fetch_contract_awards`) are only
checked on their no-network guard paths (no API key / trivial degrade).
"""

from datetime import date

import pytest

from sector_rotation.government import (
    CONGRESS_DISCLOSURE_LAG_DAYS,
    aggregate_awards_by_sector,
    aggregate_congress_by_sector,
    fetch_congressional_trades,
    naics_to_sector,
    normalize_award,
    normalize_congress_trade,
)

# A deterministic, network-free ticker->sector stub for injection.
_TICKER_SECTOR = {
    "LMT": "Industrials",
    "RTX": "Industrials",
    "XOM": "Energy",
    "CVX": "Energy",
    "JPM": "Financials",
    "PFE": "Health Care",
    "AAPL": "Information Technology",
}


def _lookup(sym):
    return _TICKER_SECTOR.get((sym or "").upper())


# --------------------------------------------------------------------------- #
# naics_to_sector
# --------------------------------------------------------------------------- #
class TestNaicsToSector:
    def test_four_digit_specific_beats_two_digit_parent(self):
        # 3344 (semiconductors) -> IT, even though 33 (manufacturing) -> Industrials
        assert naics_to_sector("334413") == "Information Technology"
        assert naics_to_sector("336411") == "Industrials"

    def test_accepts_int_and_trailing_detail(self):
        assert naics_to_sector(325110) == "Materials"
        assert naics_to_sector("2111") == "Energy"

    def test_two_digit_fallback(self):
        assert naics_to_sector("4400") == "Consumer Discretionary"
        assert naics_to_sector("62") == "Health Care"

    def test_unknown_and_garbage_return_none(self):
        assert naics_to_sector("9999") is None
        assert naics_to_sector("") is None
        assert naics_to_sector(None) is None
        assert naics_to_sector("abc") is None

    def test_result_is_canonical_sector_name(self):
        from sector_rotation.sectors import SECTOR_TO_ETF

        for code in ("3344", "2111", "3254", "522", "221"):
            sec = naics_to_sector(code)
            assert sec in SECTOR_TO_ETF


# --------------------------------------------------------------------------- #
# normalize_congress_trade
# --------------------------------------------------------------------------- #
class TestNormalizeCongressTrade:
    def test_basic_buy(self):
        rec = normalize_congress_trade(
            {
                "symbol": "lmt",
                "transactionType": "Purchase",
                "transactionDate": "2026-04-01",
                "filingDate": "2026-05-10",
                "amountFrom": 15001,
                "amountTo": 50000,
                "name": "Jane Doe",
            },
            sector_lookup=_lookup,
        )
        assert rec["symbol"] == "LMT"
        assert rec["sector"] == "Industrials"
        assert rec["side"] == "buy"
        assert rec["amount"] == pytest.approx((15001 + 50000) / 2)
        assert rec["trade_date"] == "2026-04-01"
        assert rec["filing_date"] == "2026-05-10"
        assert rec["member"] == "Jane Doe"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Purchase", "buy"),
            ("buy", "buy"),
            ("Sale (Full)", "sell"),
            ("Sale (Partial)", "sell"),
            ("sell", "sell"),
        ],
    )
    def test_side_classification(self, raw, expected):
        rec = normalize_congress_trade(
            {"symbol": "XOM", "transactionType": raw}, sector_lookup=_lookup
        )
        assert rec["side"] == expected

    def test_other_side_dropped(self):
        assert (
            normalize_congress_trade(
                {"symbol": "XOM", "transactionType": "exchange"},
                sector_lookup=_lookup,
            )
            is None
        )

    def test_missing_symbol_dropped(self):
        assert (
            normalize_congress_trade(
                {"transactionType": "Purchase"}, sector_lookup=_lookup
            )
            is None
        )

    def test_unresolved_ticker_keeps_row_with_none_sector(self):
        rec = normalize_congress_trade(
            {"symbol": "ZZZZ", "transactionType": "buy"}, sector_lookup=_lookup
        )
        assert rec is not None
        assert rec["sector"] is None

    def test_explicit_amount_preferred_over_range(self):
        rec = normalize_congress_trade(
            {"symbol": "JPM", "transactionType": "buy", "amount": 123456,
             "amountFrom": 1, "amountTo": 2},
            sector_lookup=_lookup,
        )
        assert rec["amount"] == 123456


# --------------------------------------------------------------------------- #
# aggregate_congress_by_sector
# --------------------------------------------------------------------------- #
class TestAggregateCongressBySector:
    def _sample(self):
        return [
            {"symbol": "LMT", "transactionType": "Purchase", "amountFrom": 1000, "amountTo": 3000},
            {"symbol": "RTX", "transactionType": "Purchase", "amountFrom": 1000, "amountTo": 1000},
            {"symbol": "LMT", "transactionType": "Purchase", "amountFrom": 0, "amountTo": 2000},
            {"symbol": "XOM", "transactionType": "Sale (Full)", "amountFrom": 5000, "amountTo": 5000},
            {"symbol": "CVX", "transactionType": "buy", "amountFrom": 1000, "amountTo": 1000},
            {"symbol": "ZZZZ", "transactionType": "buy", "amountFrom": 1000, "amountTo": 1000},
        ]

    def test_counts_and_ratios(self):
        out = aggregate_congress_by_sector(
            self._sample(), sector_lookup=_lookup, asof=date(2026, 5, 29)
        )
        ind = out["sectors"]["Industrials"]
        assert ind["n_buys"] == 3 and ind["n_sells"] == 0
        assert ind["net_buys"] == 3
        assert ind["buy_ratio"] == 1.0
        assert ind["flag"] == "accumulate"

        energy = out["sectors"]["Energy"]
        # XOM sell + CVX buy -> 1 buy / 1 sell
        assert energy["n_buys"] == 1 and energy["n_sells"] == 1
        assert energy["buy_ratio"] == 0.5
        assert energy["flag"] == "neutral"
        assert energy["net_dollars"] == pytest.approx(1000 - 5000)

    def test_unresolved_bucketed_unknown_never_flagged(self):
        out = aggregate_congress_by_sector(
            self._sample(), sector_lookup=_lookup, asof=date(2026, 5, 29)
        )
        assert "Unknown" in out["sectors"]
        assert out["sectors"]["Unknown"]["flag"] == "neutral"

    def test_distribute_flag(self):
        trades = [
            {"symbol": "XOM", "transactionType": "Sale (Full)"},
            {"symbol": "XOM", "transactionType": "Sale (Full)"},
            {"symbol": "CVX", "transactionType": "Sale (Full)"},
        ]
        out = aggregate_congress_by_sector(trades, sector_lookup=_lookup)
        assert out["sectors"]["Energy"]["buy_ratio"] == 0.0
        assert out["sectors"]["Energy"]["flag"] == "distribute"

    def test_disclosure_lag_annotation(self):
        out = aggregate_congress_by_sector(
            self._sample(),
            sector_lookup=_lookup,
            disclosure_lag_days=45,
            asof=date(2026, 5, 29),
        )
        assert out["disclosure_lag_days"] == 45
        assert out["stale_after"] == "2026-04-14"  # 2026-05-29 minus 45 days
        assert "45" in out["note"]
        # All 6 rows are buys/sells (ZZZZ is a buy, bucketed under Unknown).
        assert out["n_trades"] == 6

    def test_default_lag_constant(self):
        out = aggregate_congress_by_sector([], sector_lookup=_lookup)
        assert out["disclosure_lag_days"] == CONGRESS_DISCLOSURE_LAG_DAYS

    def test_empty_input(self):
        out = aggregate_congress_by_sector([], sector_lookup=_lookup)
        assert out["sectors"] == {}
        assert out["n_trades"] == 0

    def test_accepts_prenormalized_rows(self):
        norm = [
            normalize_congress_trade(
                {"symbol": "LMT", "transactionType": "buy"}, sector_lookup=_lookup
            )
        ]
        out = aggregate_congress_by_sector(norm, sector_lookup=_lookup)
        assert out["sectors"]["Industrials"]["n_buys"] == 1


# --------------------------------------------------------------------------- #
# normalize_award
# --------------------------------------------------------------------------- #
class TestNormalizeAward:
    def test_naics_drives_sector(self):
        rec = normalize_award(
            {
                "Recipient Name": "LOCKHEED MARTIN CORP",
                "Award Amount": 1.2e9,
                "naics_code": "336411",
                "Awarding Agency": "Department of Defense",
                "Award ID": "ABC123",
            },
            sector_lookup=_lookup,
        )
        assert rec["sector"] == "Industrials"
        assert rec["amount"] == 1.2e9
        assert rec["recipient"] == "LOCKHEED MARTIN CORP"
        assert rec["agency"] == "Department of Defense"
        assert rec["award_id"] == "ABC123"

    def test_ticker_fallback_when_no_naics(self):
        rec = normalize_award(
            {"Award Amount": 5000, "recipient_ticker": "pfe"},
            sector_lookup=_lookup,
        )
        assert rec["sector"] == "Health Care"

    def test_explicit_sector_wins(self):
        rec = normalize_award(
            {"Award Amount": 1, "sector": "Technology", "naics_code": "2111"},
            sector_lookup=_lookup,
        )
        assert rec["sector"] == "Information Technology"  # normalized alias

    def test_zero_amount_dropped(self):
        assert normalize_award({"Award Amount": 0}, sector_lookup=_lookup) is None
        assert normalize_award({}, sector_lookup=_lookup) is None

    def test_unresolved_sector_is_none(self):
        rec = normalize_award(
            {"Award Amount": 100, "naics_code": "9999"}, sector_lookup=_lookup
        )
        assert rec is not None
        assert rec["sector"] is None


# --------------------------------------------------------------------------- #
# aggregate_awards_by_sector
# --------------------------------------------------------------------------- #
class TestAggregateAwardsBySector:
    def _sample(self):
        return [
            {"Recipient Name": "LOCKHEED", "Award Amount": 1.0e9, "naics_code": "336411", "Awarding Agency": "DoD"},
            {"Recipient Name": "RAYTHEON", "Award Amount": 5.0e8, "naics_code": "3364", "Awarding Agency": "DoD"},
            {"Recipient Name": "EXXON", "Award Amount": 2.0e8, "naics_code": "2111", "Awarding Agency": "DoE"},
            {"Recipient Name": "MYSTERY LLC", "Award Amount": 1.0e6, "naics_code": "9999", "Awarding Agency": "GSA"},
        ]

    def test_value_count_and_top_awards(self):
        out = aggregate_awards_by_sector(self._sample(), sector_lookup=_lookup, top_n=5)
        ind = out["sectors"]["Industrials"]
        assert ind["count"] == 2
        assert ind["total_value"] == pytest.approx(1.5e9)
        # Top award is the largest first.
        assert ind["top_awards"][0]["recipient"] == "LOCKHEED"
        assert ind["top_awards"][0]["amount"] == pytest.approx(1.0e9)

    def test_sectors_ordered_by_value_desc(self):
        out = aggregate_awards_by_sector(self._sample(), sector_lookup=_lookup)
        keys = list(out["sectors"].keys())
        assert keys[0] == "Industrials"  # 1.5e9 dominates
        # Energy (2e8) ranks above Unknown (1e6).
        assert keys.index("Energy") < keys.index("Unknown")

    def test_unknown_bucket(self):
        out = aggregate_awards_by_sector(self._sample(), sector_lookup=_lookup)
        assert out["sectors"]["Unknown"]["total_value"] == pytest.approx(1.0e6)

    def test_top_n_truncation(self):
        awards = [
            {"Recipient Name": f"R{i}", "Award Amount": float(i), "naics_code": "336411"}
            for i in range(1, 11)
        ]
        out = aggregate_awards_by_sector(awards, sector_lookup=_lookup, top_n=3)
        ind = out["sectors"]["Industrials"]
        assert ind["count"] == 10
        assert len(ind["top_awards"]) == 3
        # Largest three: 10, 9, 8.
        assert [a["amount"] for a in ind["top_awards"]] == [10.0, 9.0, 8.0]

    def test_totals(self):
        out = aggregate_awards_by_sector(self._sample(), sector_lookup=_lookup)
        assert out["n_awards"] == 4
        assert out["total_value"] == pytest.approx(1.0e9 + 5.0e8 + 2.0e8 + 1.0e6)

    def test_empty(self):
        out = aggregate_awards_by_sector([], sector_lookup=_lookup)
        assert out["sectors"] == {}
        assert out["n_awards"] == 0
        assert out["total_value"] == 0.0


# --------------------------------------------------------------------------- #
# IO guard paths (no network)
# --------------------------------------------------------------------------- #
class TestIOGuards:
    def test_fetch_congress_no_api_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert fetch_congressional_trades("LMT") == []

    def test_fetch_congress_empty_symbol(self):
        assert fetch_congressional_trades("") == []
        assert fetch_congressional_trades(None) == []
