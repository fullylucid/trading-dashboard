"""PURE tests for the media/narrative leg (``sector_rotation.media``).

No network. These exercise the lexicon classifier, per-sector aggregation,
cross-sector bucketing, volume ranking, the normalized narrative signal, and
the top-level :func:`score_sectors` — all on crafted headline dicts. The IO
function :func:`fetch_sector_news` is NOT exercised here (no network); only its
no-key fast path is checked to confirm it degrades to ``[]`` without raising.
"""

import pytest

from sector_rotation.media import (
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    aggregate_sector_sentiment,
    bucket_sector_narrative,
    classify_headline,
    classify_headlines,
    fetch_sector_news,
    lexicon_classifier,
    narrative_signal,
    score_sectors,
    score_text,
    sentiment_trend,
)


# --------------------------------------------------------------------------- #
# Lexicon classifier
# --------------------------------------------------------------------------- #

def test_score_text_positive_negative_neutral():
    assert score_text("Chip demand strong, shares surge to record high") > 0
    assert score_text("Bank misses estimates, shares plunge on weak guidance") < 0
    assert score_text("Sector holds flat in quiet trading") == 0


def test_score_text_phrases():
    assert score_text("Company posts better than expected results") > 0
    assert score_text("Firm issues profit warning, cuts guidance") < 0


def test_score_text_empty_and_none():
    assert score_text("") == 0
    assert score_text(None) == 0


def test_lexicon_classifier_labels():
    assert lexicon_classifier("Nvidia beats, raises guidance") == POSITIVE
    assert lexicon_classifier("Banks tumble on default fears") == NEGATIVE
    assert lexicon_classifier("Utilities trade sideways") == NEUTRAL


def test_lexicon_tie_is_neutral():
    # one positive + one negative -> net 0 -> neutral
    assert lexicon_classifier("shares strong then weak") == NEUTRAL


def test_classify_headline_uses_summary_fallback():
    h = {"headline": "Sector update", "summary": "shares surge on strong demand"}
    assert classify_headline(h) == POSITIVE


def test_classify_headline_handles_non_dict_and_bad_classifier():
    assert classify_headline("not a dict") == NEUTRAL  # type: ignore[arg-type]

    def boom(_text):
        raise RuntimeError("model exploded")

    assert classify_headline({"headline": "anything"}, classifier=boom) == NEUTRAL


def test_classify_headline_unknown_label_degrades_to_neutral():
    assert classify_headline({"headline": "x"}, classifier=lambda _t: "wat") == NEUTRAL


def test_custom_classifier_is_used():
    def always_pos(_text):
        return POSITIVE

    labels = classify_headlines([{"headline": "x"}, {"headline": "y"}], always_pos)
    assert labels == [POSITIVE, POSITIVE]


# --------------------------------------------------------------------------- #
# Per-sector aggregation
# --------------------------------------------------------------------------- #

def test_aggregate_sector_sentiment_basic():
    hs = [
        {"headline": "chips surge to record high"},
        {"headline": "demand strong, sales beat"},
        {"headline": "regulatory probe weighs on outlook"},
    ]
    a = aggregate_sector_sentiment(hs)
    assert a["news_volume"] == 3
    assert a["positive"] == 2
    assert a["negative"] == 1
    assert a["neutral"] == 0
    # (2 - 1) / 3
    assert a["sentiment_score"] == pytest.approx(1 / 3)


def test_aggregate_empty_no_division_by_zero():
    a = aggregate_sector_sentiment([])
    assert a["news_volume"] == 0
    assert a["sentiment_score"] == 0.0
    assert (a["positive"], a["negative"], a["neutral"]) == (0, 0, 0)


def test_aggregate_all_neutral_score_zero():
    hs = [{"headline": "sector trades flat"}, {"headline": "quiet session"}]
    a = aggregate_sector_sentiment(hs)
    assert a["news_volume"] == 2
    assert a["neutral"] == 2
    assert a["sentiment_score"] == 0.0


def test_sentiment_score_bounds():
    pos = aggregate_sector_sentiment([{"headline": "strong beat surge rally"}])
    neg = aggregate_sector_sentiment([{"headline": "weak miss plunge crash"}])
    assert pos["sentiment_score"] == pytest.approx(1.0)
    assert neg["sentiment_score"] == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
# Sentiment trend
# --------------------------------------------------------------------------- #

def test_sentiment_trend():
    assert sentiment_trend(0.4, 0.1) == pytest.approx(0.3)
    assert sentiment_trend(-0.2, 0.2) == pytest.approx(-0.4)


def test_sentiment_trend_no_prior():
    assert sentiment_trend(0.4, None) is None


# --------------------------------------------------------------------------- #
# Bucketing
# --------------------------------------------------------------------------- #

def test_bucket_tailwind_headwind_neutral():
    assert bucket_sector_narrative(0.5, 20, 10.0) == "Tailwind"
    assert bucket_sector_narrative(-0.5, 20, 10.0) == "Headwind"
    # loud tone, thin volume -> neutral
    assert bucket_sector_narrative(0.5, 3, 10.0) == "Neutral"
    # high volume, flat tone (inside band) -> neutral
    assert bucket_sector_narrative(0.02, 20, 10.0) == "Neutral"


def test_bucket_threshold_is_inclusive():
    # volume exactly at threshold counts as "high volume"
    assert bucket_sector_narrative(0.5, 10, 10.0) == "Tailwind"


def test_bucket_band_edges():
    # just outside the default 0.1 band flips directional
    assert bucket_sector_narrative(0.11, 50, 5.0) == "Tailwind"
    assert bucket_sector_narrative(-0.11, 50, 5.0) == "Headwind"
    # exactly on band edge stays neutral (strict comparison)
    assert bucket_sector_narrative(0.1, 50, 5.0) == "Neutral"


# --------------------------------------------------------------------------- #
# Narrative signal
# --------------------------------------------------------------------------- #

def test_narrative_signal_extremes():
    # 1.0*50*0.7 + (1.0-0.5)*30*0.3 = 35 + 4.5 = 39.5
    assert narrative_signal(1.0, 1.0) == pytest.approx(39.5)
    assert narrative_signal(0.0, 0.5) == pytest.approx(0.0)
    assert narrative_signal(-1.0, 0.0) == pytest.approx(-39.5)


def test_narrative_signal_sentiment_dominates_volume():
    # 70/30 weighting: a strong negative tone outweighs being the loudest sector
    assert narrative_signal(-0.8, 1.0) < 0


# --------------------------------------------------------------------------- #
# score_sectors (top-level pure entry point)
# --------------------------------------------------------------------------- #

def _h(text):
    return {"headline": text}


def test_score_sectors_shape_and_bucketing():
    news = {
        # loud + positive -> Tailwind
        "XLK": [_h("chips surge"), _h("demand strong"), _h("record high beat"), _h("rally")],
        # loud + negative -> Headwind
        "XLF": [_h("banks plunge"), _h("default fears"), _h("weak guidance"), _h("probe")],
        # thin volume -> Neutral regardless of tone
        "XLE": [_h("oil rallies")],
    }
    res = score_sectors(news)

    assert set(res) == {"XLK", "XLF", "XLE"}
    # canonical sector name resolved from ETF
    assert res["XLK"]["sector"] == "Information Technology"

    assert res["XLK"]["bucket"] == "Tailwind"
    assert res["XLK"]["sentiment_score"] > 0
    assert res["XLF"]["bucket"] == "Headwind"
    assert res["XLF"]["sentiment_score"] < 0
    # XLE has below-median volume -> Neutral even though tone is positive
    assert res["XLE"]["bucket"] == "Neutral"

    # narrative signals point the expected directions
    assert res["XLK"]["narrative_signal"] > 0
    assert res["XLF"]["narrative_signal"] < 0


def test_score_sectors_volume_rank_monotonic():
    news = {
        "XLK": [_h("a"), _h("b"), _h("c")],  # loudest
        "XLF": [_h("a"), _h("b")],
        "XLE": [_h("a")],  # quietest
    }
    res = score_sectors(news)
    assert res["XLK"]["volume_rank"] == pytest.approx(1.0)
    assert res["XLE"]["volume_rank"] == pytest.approx(0.0)
    assert 0.0 < res["XLF"]["volume_rank"] < 1.0


def test_score_sectors_equal_volumes_rank_half():
    news = {"XLK": [_h("a")], "XLF": [_h("b")], "XLE": [_h("c")]}
    res = score_sectors(news)
    for k in news:
        assert res[k]["volume_rank"] == pytest.approx(0.5)


def test_score_sectors_trend_uses_prior():
    news = {"XLK": [_h("strong beat surge")]}  # score +1.0
    res = score_sectors(news, prior_scores={"XLK": 0.25})
    assert res["XLK"]["sentiment_trend"] == pytest.approx(0.75)


def test_score_sectors_trend_none_without_prior():
    news = {"XLK": [_h("strong beat")]}
    res = score_sectors(news)
    assert res["XLK"]["sentiment_trend"] is None


def test_score_sectors_empty_input():
    assert score_sectors({}) == {}


def test_score_sectors_non_etf_key_passthrough():
    # a non-ETF key resolves "sector" to the key itself (etf_to_sector -> None)
    res = score_sectors({"AAPL": [_h("strong beat surge")]})
    assert res["AAPL"]["sector"] == "AAPL"


def test_score_sectors_custom_classifier():
    def always_neg(_text):
        return NEGATIVE

    news = {"XLK": [_h("anything"), _h("else"), _h("loud")]}
    res = score_sectors(news, classifier=always_neg)
    assert res["XLK"]["sentiment_score"] == pytest.approx(-1.0)
    assert res["XLK"]["bucket"] == "Headwind"


# --------------------------------------------------------------------------- #
# IO degradation (no network exercised)
# --------------------------------------------------------------------------- #

def test_fetch_sector_news_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert fetch_sector_news("XLK") == []


def test_fetch_sector_news_blank_symbol_returns_empty():
    assert fetch_sector_news("") == []
    assert fetch_sector_news("   ") == []
