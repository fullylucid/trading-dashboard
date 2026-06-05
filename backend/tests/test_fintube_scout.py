"""Unit tests for fintube.scout._qualifies — the relevance gate for discovered videos.

This predicate decides what an unvetted, auto-discovered video has to clear to reach the
feed/Telegram. Pin the tiers: a hard threshold, a strong-relevance auto-pass, and the
worth_sharing fallback when the model declines to score.
"""

from fintube.scout import MIN_RELEVANCE, STRONG_RELEVANCE, _qualifies


def _doc(distill):
    return {"video_id": "v", "title": "t", "distill": distill}


def test_no_distill_fails():
    assert _qualifies(_doc(None), MIN_RELEVANCE) is False


def test_distill_not_a_dict_fails():
    assert _qualifies({"distill": "oops"}, MIN_RELEVANCE) is False


def test_strong_relevance_auto_passes_even_if_not_worth_sharing():
    d = _doc({"relevance": STRONG_RELEVANCE + 0.05, "worth_sharing": False})
    assert _qualifies(d, MIN_RELEVANCE) is True


def test_above_threshold_and_worth_sharing_passes():
    d = _doc({"relevance": MIN_RELEVANCE + 0.05, "worth_sharing": True})
    assert _qualifies(d, MIN_RELEVANCE) is True


def test_above_threshold_but_explicitly_not_worth_sharing_fails():
    # mid-relevance + explicit thumbs-down -> drop
    d = _doc({"relevance": MIN_RELEVANCE + 0.05, "worth_sharing": False})
    assert _qualifies(d, MIN_RELEVANCE) is False


def test_below_threshold_fails():
    d = _doc({"relevance": MIN_RELEVANCE - 0.1, "worth_sharing": True})
    assert _qualifies(d, MIN_RELEVANCE) is False


def test_unscored_falls_back_to_worth_sharing():
    assert _qualifies(_doc({"worth_sharing": True}), MIN_RELEVANCE) is True
    assert _qualifies(_doc({"worth_sharing": False}), MIN_RELEVANCE) is False
    assert _qualifies(_doc({}), MIN_RELEVANCE) is False


def test_custom_min_relevance_respected():
    d = _doc({"relevance": 0.5, "worth_sharing": True})
    assert _qualifies(d, 0.4) is True   # clears a lenient bar
    assert _qualifies(d, 0.6) is False  # fails a stricter bar
