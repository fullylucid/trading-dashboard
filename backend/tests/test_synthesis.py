"""PURE unit tests for sector_rotation.synthesis (fuse_rotation + map_to_companies).

No network, no disk: every test feeds hand-built stream rows into the pure
fusion / mapping functions and asserts the schema, the IN/OUT signing, graceful
degradation when streams are missing, and the lagging-only confidence damping.
The orchestrator ``run_sector_rotation`` is IO and is NOT exercised here.

Run:
    ~/.config/agent-bridge/testvenv/bin/python -m pytest backend/tests/test_synthesis.py -q
"""

from __future__ import annotations

import math

import pytest

from sector_rotation.synthesis import (
    CONF_ALERT,
    CONF_WATCH,
    SCORE_IN,
    SCORE_OUT,
    STREAM_WEIGHTS,
    fuse_rotation,
    map_to_companies,
)


# --------------------------------------------------------------------------- #
# sample stream-row builders
# --------------------------------------------------------------------------- #
def _market(quadrant="Leading", rs_ratio=104.0, rs_momentum=103.0, roc=None):
    return {
        "sector": None,
        "quadrant": quadrant,
        "rs_ratio": rs_ratio,
        "rs_momentum": rs_momentum,
        "roc": roc or {"1w": 1.0, "1m": 3.0, "3m": 6.0},
        "money_flow": {"obv": None, "obv_rising": None, "rvol": None},
    }


def _smart_money(score=70.0, lagging=False):
    return {"sector": "x", "etf": "x", "score": score, "lagging": lagging}


def _media(narrative_signal=30.0, sentiment_score=0.6):
    return {"narrative_signal": narrative_signal, "sentiment_score": sentiment_score}


def _catalyst(catalyst_score=20.0):
    return {"catalyst_score": catalyst_score, "pressure": 40.0}


def _government(buy_ratio=0.8, flag="accumulate", award_value=0.0):
    row = {"congress": {"buy_ratio": buy_ratio, "flag": flag}}
    if award_value:
        row["awards"] = {"total_value": award_value}
    return row


# --------------------------------------------------------------------------- #
# fuse_rotation — schema
# --------------------------------------------------------------------------- #
def test_fuse_rotation_output_schema():
    out = fuse_rotation({
        "Information Technology": {
            "market": _market(),
            "smart_money": _smart_money(),
            "media": _media(),
            "catalyst": _catalyst(),
            "government": _government(),
        }
    })
    assert set(out) == {"Information Technology"}
    row = out["Information Technology"]
    expected_keys = {
        "sector", "etf", "rotation_score", "confidence", "status", "alert",
        "phase", "components", "present", "lagging_only",
    }
    assert set(row) == expected_keys
    assert row["sector"] == "Information Technology"
    assert row["etf"] == "XLK"
    assert -100.0 <= row["rotation_score"] <= 100.0
    assert 0.0 <= row["confidence"] <= 100.0
    assert row["status"] in {"rotating-IN", "rotating-OUT", "neutral"}
    assert row["alert"] in {"immediate", "watch", "log"}
    assert row["phase"] == "Leading"
    assert set(row["components"]) == set(STREAM_WEIGHTS)
    assert set(row["present"]) == set(STREAM_WEIGHTS)  # all 5 present


def test_components_are_floats_when_present_none_when_absent():
    out = fuse_rotation({
        "Energy": {"market": _market(quadrant="Leading")}  # only price present
    })
    comp = out["Energy"]["components"]
    assert isinstance(comp["market"], float)
    for s in ("smart_money", "media", "catalyst", "government"):
        assert comp[s] is None
    assert out["Energy"]["present"] == ["market"]


# --------------------------------------------------------------------------- #
# fuse_rotation — signing
# --------------------------------------------------------------------------- #
def test_all_bullish_streams_rotate_in():
    out = fuse_rotation({
        "Financials": {
            "market": _market(quadrant="Leading", rs_ratio=106, rs_momentum=105),
            "smart_money": _smart_money(score=90),
            "media": _media(narrative_signal=45),
            "catalyst": _catalyst(catalyst_score=40),
            "government": _government(buy_ratio=0.9),
        }
    })
    row = out["Financials"]
    assert row["rotation_score"] >= SCORE_IN
    assert row["status"] == "rotating-IN"
    assert row["phase"] == "Leading"


def test_all_bearish_streams_rotate_out():
    out = fuse_rotation({
        "Utilities": {
            "market": _market(quadrant="Lagging", rs_ratio=94, rs_momentum=95,
                              roc={"1w": -1.0, "1m": -4.0, "3m": -8.0}),
            "media": _media(narrative_signal=-40, sentiment_score=-0.8),
            "catalyst": _catalyst(catalyst_score=-30),
            "government": _government(buy_ratio=0.1, flag="distribute"),
        }
    })
    row = out["Utilities"]
    assert row["rotation_score"] <= SCORE_OUT
    assert row["status"] == "rotating-OUT"
    assert row["phase"] == "Lagging"


def test_market_backbone_dominates_a_single_dissenting_tilt():
    # Strong bearish price + one mild bullish narrative -> still net OUT,
    # because market carries 0.50 of the weight.
    out = fuse_rotation({
        "Materials": {
            "market": _market(quadrant="Lagging", rs_ratio=90, rs_momentum=90,
                              roc={"1w": -2.0, "1m": -6.0, "3m": -10.0}),
            "media": _media(narrative_signal=10),
        }
    })
    assert out["Materials"]["rotation_score"] < 0.0


def test_neutral_when_no_usable_data():
    out = fuse_rotation({"Real Estate": {}})
    row = out["Real Estate"]
    assert row["rotation_score"] == 0.0
    assert row["confidence"] == 0.0
    assert row["status"] == "neutral"
    assert row["alert"] == "log"
    assert row["present"] == []
    assert row["phase"] == "Neutral"


# --------------------------------------------------------------------------- #
# fuse_rotation — graceful degradation + weight renormalization
# --------------------------------------------------------------------------- #
def test_missing_stream_does_not_drag_toward_zero():
    # A sector seen ONLY by a strongly-bullish price stream should score close to
    # its price sub-score, not be diluted toward 0 by the absent streams.
    price_only = fuse_rotation({
        "Health Care": {"market": _market(quadrant="Leading", rs_ratio=107,
                                          rs_momentum=106)}
    })["Health Care"]
    market_sub = price_only["components"]["market"]
    # With only one present stream, the fused score == that stream's sub-score.
    assert price_only["rotation_score"] == pytest.approx(market_sub, abs=0.01)
    assert price_only["rotation_score"] > 0.0


def test_none_streams_are_tolerated():
    out = fuse_rotation({
        "Industrials": {
            "market": _market(),
            "smart_money": None,
            "media": None,
            "catalyst": None,
            "government": None,
        }
    })
    assert out["Industrials"]["present"] == ["market"]


def test_empty_input_returns_empty():
    assert fuse_rotation({}) == {}
    assert fuse_rotation(None) == {}


def test_zero_volume_media_row_is_not_counted_as_present():
    # An empty-news day yields a media row with news_volume==0 and a 0.0 signal;
    # it must not register as a present media confirmation.
    out = fuse_rotation({
        "Energy": {
            "market": _market(quadrant="Leading"),
            "media": {"news_volume": 0, "narrative_signal": 0.0,
                      "sentiment_score": 0.0},
        }
    })
    assert out["Energy"]["present"] == ["market"]
    assert out["Energy"]["components"]["media"] is None


# --------------------------------------------------------------------------- #
# fuse_rotation — confidence / lagging damping
# --------------------------------------------------------------------------- #
def test_full_coverage_agreement_yields_high_confidence():
    out = fuse_rotation({
        "Information Technology": {
            "market": _market(quadrant="Leading", rs_ratio=108, rs_momentum=107),
            "smart_money": _smart_money(score=95),
            "media": _media(narrative_signal=48),
            "catalyst": _catalyst(catalyst_score=45),
            "government": _government(buy_ratio=0.95, award_value=1e7),
        }
    })
    assert out["Information Technology"]["confidence"] >= CONF_WATCH


def test_lagging_only_caps_confidence_below_watch_band():
    # Only the (always-lagging) government stream fired.
    out = fuse_rotation({
        "Energy": {"government": _government(buy_ratio=0.95, flag="accumulate")}
    })
    row = out["Energy"]
    assert row["lagging_only"] is True
    assert row["confidence"] < CONF_WATCH  # never reaches the 60 watch band alone
    assert row["alert"] == "log"


def test_lagging_only_cap_is_actually_applied_not_incidental():
    # DISCRIMINATING: drive the lagging-only government stream to MAX strength so
    # its *uncapped* confidence would breach the 55 cap (~58.9). The result must
    # be pinned at the 55.0 cap — proving the cap fires, not that the natural
    # confidence merely happened to land low. A regression removing the cap would
    # let this read climb above 55 (toward the 60 watch band) on stale money.
    from sector_rotation.synthesis import _confidence, STREAM_WEIGHTS

    out = fuse_rotation({
        "Energy": {
            "government": {
                "congress": {"buy_ratio": 1.0, "flag": "accumulate"},
                "awards": {"total_value": 1e9},
            }
        }
    })
    row = out["Energy"]
    assert row["lagging_only"] is True
    # Uncapped confidence for this max-strength lagging read is > the 55 cap...
    uncapped = _confidence(
        row["rotation_score"], STREAM_WEIGHTS["government"], 1, 1,
        only_lagging=False,
    )
    assert uncapped > 55.0, "fixture must exercise the cap (uncapped should exceed it)"
    # ...so the capped, reported confidence must be exactly the 55.0 ceiling.
    assert row["confidence"] == pytest.approx(55.0)


def test_empty_market_block_excluded_so_strong_signal_not_diluted():
    # DISCRIMINATING: a Neutral, value-less market block (no quadrant edge, no
    # ratio/momentum/ROC) must NOT count as a present stream. If it did, its 0.0
    # sub-score would enter the blend at the heavy 0.50 market weight and drag a
    # strong non-market signal toward zero (100 -> ~26). The market stream is the
    # one with the largest weight, so this is the worst NaN/empty-poison case.
    empty_market = {
        "quadrant": "Neutral",
        "rs_ratio": None,
        "rs_momentum": None,
        "roc": {"1w": None, "1m": None, "3m": None},
        "money_flow": {},
    }
    out = fuse_rotation({
        "Energy": {
            "market": empty_market,
            "smart_money": _smart_money(score=100.0),
        }
    })
    row = out["Energy"]
    assert "market" not in row["present"]
    assert row["present"] == ["smart_money"]
    assert row["components"]["market"] is None
    # Score rides on the lone strong smart-money sub-score, undiluted.
    assert row["rotation_score"] == pytest.approx(100.0)


def test_results_sorted_by_descending_score():
    out = fuse_rotation({
        "Financials": {"market": _market(quadrant="Lagging", rs_ratio=92,
                                         rs_momentum=92,
                                         roc={"1w": -2, "1m": -5, "3m": -9})},
        "Information Technology": {"market": _market(quadrant="Leading",
                                                     rs_ratio=108,
                                                     rs_momentum=107)},
    })
    scores = [r["rotation_score"] for r in out.values()]
    assert scores == sorted(scores, reverse=True)
    assert list(out)[0] == "Information Technology"


# --------------------------------------------------------------------------- #
# map_to_companies
# --------------------------------------------------------------------------- #
def _rotation_fixture():
    return fuse_rotation({
        "Information Technology": {  # rotating-IN
            "market": _market(quadrant="Leading", rs_ratio=108, rs_momentum=107),
            "smart_money": _smart_money(score=90),
            "media": _media(narrative_signal=45),
        },
        "Utilities": {  # rotating-OUT
            "market": _market(quadrant="Lagging", rs_ratio=92, rs_momentum=92,
                              roc={"1w": -2, "1m": -6, "3m": -10}),
            "media": _media(narrative_signal=-40, sentiment_score=-0.8),
        },
        "Energy": {  # neutral
            "market": _market(quadrant="Improving", rs_ratio=99, rs_momentum=101,
                              roc={"1w": 0.1, "1m": 0.2, "3m": 0.1}),
        },
    })


def test_map_to_companies_tags_tailwind_and_risk():
    rotation = _rotation_fixture()
    lookup = {
        "AAPL": "Information Technology",
        "NVDA": "Information Technology",
        "DUK": "Utilities",
        "ZZZZ": None,  # unresolvable sector
    }
    result = map_to_companies(
        rotation, ["AAPL", "NVDA", "DUK", "ZZZZ"],
        sector_lookup=lambda s: lookup.get(s),
    )

    assert set(result) == {"tagged", "tailwinds", "risks", "top_in_sectors"}
    tags = {t["symbol"]: t["tag"] for t in result["tagged"]}
    assert tags["AAPL"] == "tailwind"
    assert tags["NVDA"] == "tailwind"
    assert tags["DUK"] == "risk"
    assert tags["ZZZZ"] == "unknown"

    assert set(result["tailwinds"]) == {"AAPL", "NVDA"}
    assert result["risks"] == ["DUK"]


def test_map_to_companies_tagged_row_schema():
    rotation = _rotation_fixture()
    result = map_to_companies(
        rotation, ["AAPL"], sector_lookup=lambda s: "Information Technology"
    )
    row = result["tagged"][0]
    assert set(row) == {
        "symbol", "sector", "etf", "rotation_score", "confidence",
        "status", "alert", "phase", "tag",
    }
    assert row["symbol"] == "AAPL"
    assert row["sector"] == "Information Technology"
    assert row["etf"] == "XLK"
    assert row["tag"] == "tailwind"
    assert row["phase"] == "Leading"


def test_map_to_companies_top_in_sectors_and_candidates():
    rotation = _rotation_fixture()
    result = map_to_companies(
        rotation, ["AAPL", "NVDA", "DUK"],
        sector_lookup=lambda s: {
            "AAPL": "Information Technology",
            "NVDA": "Information Technology",
            "DUK": "Utilities",
        }.get(s),
    )
    top = result["top_in_sectors"]
    assert top, "expected at least one rotating-IN sector"
    it = top[0]
    assert it["sector"] == "Information Technology"
    assert it["etf"] == "XLK"
    assert it["candidate_tickers"] == ["AAPL", "NVDA"]  # sorted, holdings-derived


def test_map_to_companies_holding_dict_with_inline_sector():
    rotation = _rotation_fixture()
    # Holding dict carries its own sector -> lookup must NOT be consulted.
    def _boom(_):  # pragma: no cover - should never be called
        raise AssertionError("sector_lookup should not be called")

    result = map_to_companies(
        rotation,
        [{"symbol": "AAPL", "sector": "Technology"}],  # vendor spelling
        sector_lookup=_boom,
    )
    row = result["tagged"][0]
    assert row["symbol"] == "AAPL"
    assert row["sector"] == "Information Technology"  # normalized
    assert row["tag"] == "tailwind"


def test_map_to_companies_dedupes_and_handles_empty():
    rotation = _rotation_fixture()
    result = map_to_companies(
        rotation, ["AAPL", "aapl", "AAPL"],
        sector_lookup=lambda s: "Information Technology",
    )
    assert len(result["tagged"]) == 1

    empty = map_to_companies({}, [], sector_lookup=lambda s: None)
    assert empty["tagged"] == []
    assert empty["tailwinds"] == []
    assert empty["top_in_sectors"] == []


def test_map_to_companies_lookup_exception_degrades_to_unknown():
    rotation = _rotation_fixture()

    def _raises(_):
        raise RuntimeError("network down")

    result = map_to_companies(rotation, ["AAPL"], sector_lookup=_raises)
    assert result["tagged"][0]["tag"] == "unknown"


def test_score_band_constants_are_sane():
    assert SCORE_OUT < 0 < SCORE_IN
    assert CONF_WATCH < CONF_ALERT
    assert math.isclose(sum(STREAM_WEIGHTS.values()), 1.0, abs_tol=1e-9)
