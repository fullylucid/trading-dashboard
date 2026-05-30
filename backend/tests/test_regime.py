"""Unit tests for backend/analytics/regime.py — the PURE regime_bias mapping.

These tests pass sample regime dicts (no toolkit / network) and assert that each
regime label resolves to the correct size / stop multipliers and canonical
class. The async IO wrapper (get_regime_with_bias) is not exercised here — it is
just a thin, exception-wrapped adapter over the unit-tested pure function.
"""

import math

import pytest

from analytics import regime as rg


# --------------------------------------------------------------------------- #
# expected presets (mirror the module's documented mapping)
# --------------------------------------------------------------------------- #
UPTREND = {"size_multiplier": 1.0, "stop_atr_multiplier": 2.0}
CHOPPY = {"size_multiplier": 0.7, "stop_atr_multiplier": 2.5}
DOWNTREND = {"size_multiplier": 0.5, "stop_atr_multiplier": 3.0}
NEUTRAL = {"size_multiplier": 0.7, "stop_atr_multiplier": 2.5}


def _assert_bias(bias, expected, expected_class):
    assert bias["size_multiplier"] == pytest.approx(expected["size_multiplier"])
    assert bias["stop_atr_multiplier"] == pytest.approx(expected["stop_atr_multiplier"])
    assert bias["regime_class"] == expected_class
    assert isinstance(bias["note"], str) and bias["note"]


# --------------------------------------------------------------------------- #
# trend_direction field (mapped-regime schema from _map_regime/_default_regime)
# --------------------------------------------------------------------------- #
def test_trend_direction_bullish_full_size_normal_stops():
    _assert_bias(rg.regime_bias({"trend_direction": "bullish"}), UPTREND, "uptrend")


def test_trend_direction_bearish_half_size_wider_stops():
    _assert_bias(rg.regime_bias({"trend_direction": "bearish"}), DOWNTREND, "downtrend")


def test_trend_direction_neutral_reduced_size_wider_stops():
    _assert_bias(rg.regime_bias({"trend_direction": "neutral"}), NEUTRAL, "neutral")


# --------------------------------------------------------------------------- #
# raw_regime toolkit labels: bull_calm/bear_calm are clean trends;
# bull_stressed/bear_stressed are high-vol -> choppy down-size
# --------------------------------------------------------------------------- #
def test_raw_regime_bull_calm_is_uptrend():
    _assert_bias(rg.regime_bias({"raw_regime": "bull_calm"}), UPTREND, "uptrend")


def test_raw_regime_bear_calm_is_downtrend():
    _assert_bias(rg.regime_bias({"raw_regime": "bear_calm"}), DOWNTREND, "downtrend")


def test_raw_regime_bull_stressed_is_choppy():
    # high-volatility bull -> treat as choppy: reduced size, wider stops
    _assert_bias(rg.regime_bias({"raw_regime": "bull_stressed"}), CHOPPY, "choppy")


def test_raw_regime_bear_stressed_is_choppy():
    _assert_bias(rg.regime_bias({"raw_regime": "bear_stressed"}), CHOPPY, "choppy")


def test_raw_regime_neutral_is_neutral():
    _assert_bias(rg.regime_bias({"raw_regime": "neutral"}), NEUTRAL, "neutral")


def test_raw_regime_insufficient_data_falls_back_to_neutral():
    _assert_bias(rg.regime_bias({"raw_regime": "insufficient_data"}), NEUTRAL, "neutral")


# --------------------------------------------------------------------------- #
# bare label/regime keys + free-form synonyms
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "label,expected,cls",
    [
        ("uptrend", UPTREND, "uptrend"),
        ("BULL", UPTREND, "uptrend"),
        ("downtrend", DOWNTREND, "downtrend"),
        ("crash", DOWNTREND, "downtrend"),
        ("choppy", CHOPPY, "choppy"),
        ("sideways", CHOPPY, "choppy"),
        ("range_bound", CHOPPY, "choppy"),
        ("transition", CHOPPY, "choppy"),
    ],
)
def test_bare_label_key(label, expected, cls):
    _assert_bias(rg.regime_bias({"label": label}), expected, cls)


@pytest.mark.parametrize(
    "label,expected,cls",
    [
        ("bull_calm", UPTREND, "uptrend"),
        ("bear_calm", DOWNTREND, "downtrend"),
        ("neutral", NEUTRAL, "neutral"),
    ],
)
def test_bare_regime_key(label, expected, cls):
    _assert_bias(rg.regime_bias({"regime": label}), expected, cls)


# --------------------------------------------------------------------------- #
# hmm_phase fallback (0=bear, 1=neutral, 2=bull)
# --------------------------------------------------------------------------- #
def test_hmm_phase_bull():
    _assert_bias(rg.regime_bias({"hmm_phase": 2}), UPTREND, "uptrend")


def test_hmm_phase_bear():
    _assert_bias(rg.regime_bias({"hmm_phase": 0}), DOWNTREND, "downtrend")


def test_hmm_phase_neutral():
    _assert_bias(rg.regime_bias({"hmm_phase": 1}), NEUTRAL, "neutral")


# --------------------------------------------------------------------------- #
# precedence: explicit label wins over trend_direction wins over hmm_phase
# --------------------------------------------------------------------------- #
def test_label_overrides_trend_direction_and_phase():
    # label says bull, other fields say bear -> uptrend wins
    state = {"raw_regime": "bull_calm", "trend_direction": "bearish", "hmm_phase": 0}
    _assert_bias(rg.regime_bias(state), UPTREND, "uptrend")


def test_trend_direction_used_when_label_unrecognized():
    # unrecognized label string falls through to trend_direction
    state = {"raw_regime": "???", "trend_direction": "bearish", "hmm_phase": 2}
    _assert_bias(rg.regime_bias(state), DOWNTREND, "downtrend")


def test_phase_used_when_no_label_or_trend():
    state = {"market_heat": 0.9, "hmm_phase": 2}
    _assert_bias(rg.regime_bias(state), UPTREND, "uptrend")


# --------------------------------------------------------------------------- #
# full mapped-regime dicts exactly as produced by quant_bridge
# --------------------------------------------------------------------------- #
def test_full_default_regime_dict_is_neutral():
    default_regime = {
        "hmm_phase": 1,
        "volatility_regime": "normal",
        "market_heat": 0.5,
        "trend_direction": "neutral",
        "estimated_probability": 0.33,
    }
    _assert_bias(rg.regime_bias(default_regime), NEUTRAL, "neutral")


def test_full_mapped_bull_regime():
    mapped = {
        "hmm_phase": 2,
        "volatility_regime": "low",
        "market_heat": 0.7,
        "trend_direction": "bullish",
        "estimated_probability": 0.82,
        "raw_regime": "bull_calm",
    }
    _assert_bias(rg.regime_bias(mapped), UPTREND, "uptrend")


# --------------------------------------------------------------------------- #
# defensive / degenerate inputs -> neutral default, never raises
# --------------------------------------------------------------------------- #
def test_none_input_neutral():
    _assert_bias(rg.regime_bias(None), NEUTRAL, "neutral")


def test_empty_dict_neutral():
    _assert_bias(rg.regime_bias({}), NEUTRAL, "neutral")


def test_non_mapping_input_neutral():
    # a list is not a Mapping -> neutral
    _assert_bias(rg.regime_bias(["bull"]), NEUTRAL, "neutral")


def test_unrecognized_strings_neutral():
    _assert_bias(rg.regime_bias({"label": "wat", "trend_direction": "spicy"}), NEUTRAL, "neutral")


# --------------------------------------------------------------------------- #
# purity: returned dict is a fresh copy; mutating it does not corrupt presets
# --------------------------------------------------------------------------- #
def test_returned_dict_is_isolated_copy():
    a = rg.regime_bias({"trend_direction": "bullish"})
    a["size_multiplier"] = 999.0
    b = rg.regime_bias({"trend_direction": "bullish"})
    assert b["size_multiplier"] == pytest.approx(1.0)


def test_size_multiplier_ordering_invariant():
    """Sanity: uptrend >= choppy/neutral >= downtrend on size; stops invert."""
    up = rg.regime_bias({"label": "bull_calm"})
    chop = rg.regime_bias({"label": "choppy"})
    down = rg.regime_bias({"label": "bear_calm"})
    assert up["size_multiplier"] >= chop["size_multiplier"] >= down["size_multiplier"]
    assert up["stop_atr_multiplier"] <= chop["stop_atr_multiplier"] <= down["stop_atr_multiplier"]
    assert not math.isnan(up["size_multiplier"])
