"""Unit tests for backend/analytics/alerts.py — the PURE alert/what-if layer.

Exercises three pure functions with hand-built sample inputs (no network, no
disk):

- ``score_alert``      : a high-confluence bullish case -> "alert"; a weak case
                         -> "log"; a bearish-confluence case; regime tilt; empty.
- ``what_if_add``      : incremental beta / HHI / ENS / VaR delta math against a
                         known 2-name book, plus the empty-book and concentration
                         cases.
- ``rebalancing_suggestions`` : trim (oversized), diversify (low ENS), and
                         correlation-redundancy flags.
"""

import math

import pytest

from analytics import alerts as al


# --------------------------------------------------------------------------- #
# score_alert
# --------------------------------------------------------------------------- #
def test_high_confluence_bullish_fires_alert():
    """Several agreeing bullish streams -> 'alert' bucket, bullish direction."""
    res = al.score_alert(
        symbol="NVDA",
        signals={
            "roc": 18.0,                     # strong momentum
            "relative_strength": 12.0,        # leading SPY
            "rsi": 62.0,                      # healthy, not overbought
            "macd": {"macd": 2.0, "signal": 1.0, "hist": 1.0},  # +hist
            "divergence": None,
            "ma_structure": {"golden_cross": True, "stacked_bullish": True,
                             "above_50": True, "above_200": True, "death_cross": False},
            "rvol": 2.5,                      # volume surge
            "pct_of_52w_range": 95.0,         # near highs
        },
        insider={"has_cluster": True, "confidence": 85.0, "num_insiders": 3},
        regime={"regime_class": "uptrend"},
        risk={"unrealized_r": 2.5},
        sector_rotation={"status": "rotating-in", "rotation_score": 60.0},
        composite_score=8.5,
    )
    assert res["direction"] == "bullish"
    assert res["confidence"] >= al.ALERT_THRESHOLD
    assert res["bucket"] == "alert"
    # Confluence: many independent factors, not one oracle.
    contributing = [f for f in res["contributing_factors"] if f["direction"] == "bullish"]
    assert len(contributing) >= 5


def test_weak_case_logs_only():
    """A single mild signal -> below 60 -> 'log'."""
    res = al.score_alert(
        symbol="MEH",
        signals={
            "roc": 1.0,                       # below the +/-5% gate -> ignored
            "rsi": 51.0,                      # neutral
            "macd": {"hist": 0.2},            # mild +10 only
        },
    )
    assert res["bucket"] == "log"
    assert res["confidence"] < al.WATCH_THRESHOLD


def test_empty_inputs_score_zero_neutral():
    res = al.score_alert(symbol="EMPTY")
    assert res["confidence"] == 0.0
    assert res["bucket"] == "log"
    assert res["direction"] == "neutral"
    assert res["contributing_factors"] == []


def test_bearish_confluence_direction():
    res = al.score_alert(
        symbol="DOWN",
        signals={
            "roc": -15.0,
            "relative_strength": -10.0,
            "rsi": 78.0,                      # overbought (bearish)
            "macd": {"hist": -1.0},
            "divergence": "bearish",
            "ma_structure": {"death_cross": True, "above_200": False},
            "pct_of_52w_range": 5.0,          # near lows
        },
        risk={"unrealized_r": -0.8},
        sector_rotation={"status": "rotating-out", "rotation_score": -50.0},
        composite_score=2.0,
    )
    assert res["direction"] == "bearish"
    assert res["confidence"] >= al.WATCH_THRESHOLD


def test_regime_downtrend_discounts_longs():
    """The same bullish setup scores lower in a downtrend regime than neutral."""
    sig = {
        "roc": 18.0,
        "relative_strength": 12.0,
        "macd": {"hist": 1.0},
        "ma_structure": {"golden_cross": True},
    }
    neutral = al.score_alert(symbol="X", signals=sig, regime={"regime_class": "neutral"})
    downtrend = al.score_alert(symbol="X", signals=sig, regime={"regime_class": "downtrend"})
    assert downtrend["confidence"] < neutral["confidence"]
    assert downtrend["score_breakdown"]["bullish"] == pytest.approx(
        neutral["score_breakdown"]["bullish"] * 0.7, rel=1e-6
    )


def test_no_single_factor_reaches_alert_alone():
    """One very strong stream alone cannot clear 80 (confluence required)."""
    res = al.score_alert(
        symbol="ONE",
        insider={"has_cluster": True, "confidence": 100.0, "num_insiders": 6},
    )
    assert res["confidence"] <= al._MAX_PER_FACTOR
    assert res["bucket"] == "log"


# --------------------------------------------------------------------------- #
# what_if_add — delta math
# --------------------------------------------------------------------------- #
def _two_name_book():
    """A known 2-name, equal-weight book with portfolio_value for exact math."""
    return {
        "portfolio_value": 100.0,
        "weights": {"AAA": 0.5, "BBB": 0.5},
        "beta_to_spy": 1.0,
        "per_holding_beta": {"AAA": 1.2, "BBB": 0.8},
        "hhi": 0.5,                  # equal 2 names -> 1/2
        "effective_number": 2.0,
        "var_95": {"parametric": 0.02},
    }


def test_what_if_add_weight_and_concentration_math():
    """Adding $100 to a $100 book -> new name is 50%, existing scaled to 25/25."""
    pr = _two_name_book()
    res = al.what_if_add(pr, {"symbol": "CCC", "market_value": 100.0, "beta": 1.0})

    assert res["new_portfolio_value"] == pytest.approx(200.0)
    assert res["new_weight"] == pytest.approx(0.5)

    # New weights: AAA=0.25, BBB=0.25, CCC=0.5 -> HHI = .0625+.0625+.25 = 0.375
    assert res["hhi"]["before"] == pytest.approx(0.5)
    assert res["hhi"]["after"] == pytest.approx(0.375)
    assert res["hhi"]["delta"] == pytest.approx(-0.125)

    # ENS = 1/HHI: before 2.0, after 1/0.375 = 2.6667
    assert res["effective_number"]["before"] == pytest.approx(2.0)
    assert res["effective_number"]["after"] == pytest.approx(1.0 / 0.375)

    # Big 50% add -> concentration flag.
    assert res["concentration_flag"] is True


def test_what_if_add_beta_blend():
    """beta_after = (1-wa)*beta_old + wa*beta_added with wa=0.2."""
    pr = _two_name_book()
    # Add $25 to a $100 book -> wa = 25/125 = 0.2
    res = al.what_if_add(pr, {"symbol": "DDD", "market_value": 25.0, "beta": 2.0})
    wa = 25.0 / 125.0
    expected_beta = (1.0 - wa) * 1.0 + wa * 2.0
    assert res["new_weight"] == pytest.approx(wa)
    assert res["beta"]["after"] == pytest.approx(expected_beta)
    assert res["beta"]["delta"] == pytest.approx(expected_beta - 1.0)


def test_what_if_add_var_scales_by_beta_ratio():
    """First-order VaR proxy scales by |beta_after / beta_old|."""
    pr = _two_name_book()
    res = al.what_if_add(pr, {"symbol": "EEE", "market_value": 100.0, "beta": 2.0})
    wa = 0.5
    beta_after = (1.0 - wa) * 1.0 + wa * 2.0  # 1.5
    expected_var = 0.02 * abs(beta_after / 1.0)
    assert res["var_95_parametric"]["after"] == pytest.approx(expected_var)


def test_what_if_add_empty_book_is_100pct():
    res = al.what_if_add({}, {"symbol": "ONLY", "market_value": 50.0, "beta": 1.3})
    assert res["new_weight"] == pytest.approx(1.0)
    assert res["concentration_flag"] is True
    # ENS of a single name is 1.0
    assert res["effective_number"]["after"] == pytest.approx(1.0)


def test_what_if_add_rejects_nonpositive_value():
    res = al.what_if_add(_two_name_book(), {"symbol": "BAD", "market_value": 0.0})
    assert "error" in res


def test_what_if_add_unknown_beta_defaults_to_one():
    pr = _two_name_book()
    res = al.what_if_add(pr, {"symbol": "NEW", "market_value": 100.0})  # no beta given, not in book
    wa = 0.5
    expected = (1.0 - wa) * 1.0 + wa * 1.0  # assumed beta 1.0 -> stays 1.0
    assert res["beta"]["after"] == pytest.approx(expected)
    assert any("assumed market beta" in n for n in res["notes"])


# --------------------------------------------------------------------------- #
# rebalancing_suggestions
# --------------------------------------------------------------------------- #
def test_rebalancing_trim_flag_for_oversized_position():
    pr = {
        "weights": {"BIG": 0.40, "A": 0.20, "B": 0.20, "C": 0.20},
        "effective_number": 3.6,
        "hhi": 0.28,
    }
    res = al.rebalancing_suggestions(pr, max_position_weight=0.25)
    trims = [f for f in res["flags"] if f["type"] == "trim"]
    assert len(trims) == 1
    assert trims[0]["symbol"] == "BIG"
    assert res["metrics"]["largest_position"] == "BIG"


def test_rebalancing_diversify_flag_for_low_ens():
    pr = {"weights": {"X": 0.6, "Y": 0.4}, "effective_number": 1.9, "hhi": 0.52}
    res = al.rebalancing_suggestions(pr, min_effective_number=5.0)
    assert any(f["type"] == "diversify" for f in res["flags"])


def test_rebalancing_correlation_redundancy_pair():
    pr = {
        "weights": {"AAA": 0.3, "BBB": 0.1, "CCC": 0.6},
        "effective_number": 6.0,            # don't trip diversify
        "correlation_matrix": {
            "AAA": {"AAA": 1.0, "BBB": 0.92, "CCC": 0.1},
            "BBB": {"AAA": 0.92, "BBB": 1.0, "CCC": 0.2},
            "CCC": {"AAA": 0.1, "BBB": 0.2, "CCC": 1.0},
        },
    }
    res = al.rebalancing_suggestions(pr, high_corr_threshold=0.8, max_position_weight=0.7)
    redundant = [f for f in res["flags"] if f["type"] == "correlation_redundancy"]
    assert len(redundant) == 1
    assert sorted(redundant[0]["pair"]) == ["AAA", "BBB"]
    # The smaller-weight name (BBB at 0.1) is suggested for trimming.
    assert redundant[0]["suggested_trim"] == "BBB"
    # Pair reported once (no AAA/BBB and BBB/AAA duplicate).
    assert redundant[0]["correlation"] == pytest.approx(0.92)


def test_rebalancing_balanced_book_no_flags():
    pr = {
        "weights": {f"S{i}": 0.1 for i in range(10)},   # 10 equal names
        "effective_number": 10.0,
        "hhi": 0.1,
        "correlation_matrix": {f"S{i}": {f"S{j}": (1.0 if i == j else 0.1)
                                         for j in range(10)} for i in range(10)},
    }
    res = al.rebalancing_suggestions(pr)
    assert res["flags"] == []
    assert "balanced" in res["summary"].lower()


def test_rebalancing_empty_input_no_flags():
    res = al.rebalancing_suggestions(None)
    assert res["flags"] == []
    assert res["metrics"]["num_holdings"] == 0
