"""Unit tests for fintube.find_video — query cleanup + candidate ranking.

The async find_from_image flow needs a live VLM (and pytest-asyncio, absent here); we pin
the sync seams it's built from: VLM title-read normalization and similarity ranking
(including the 'Title - Channel' split).
"""

from fintube import find_video
from fintube.find_video import _clean_query, rank_candidates


def test_clean_query_strips_quotes_and_whitespace():
    assert _clean_query('  "NVDA  breakout\n now"  ') == "NVDA breakout now"


def test_clean_query_caps_length():
    assert len(_clean_query("x" * 300)) == 120


def test_clean_query_empty():
    assert _clean_query("") == ""
    assert _clean_query(None) == ""  # type: ignore[arg-type]


def _hit(vid, title):
    return {"video_id": vid, "title": title, "url": f"https://youtu.be/{vid}"}


def test_rank_orders_by_title_similarity():
    hits = [
        _hit("aaaaaaaaaa1", "Totally unrelated cooking video"),
        _hit("bbbbbbbbbb2", "NVDA breakout analysis 2026"),
        _hit("cccccccccc3", "NVDA breakout"),
    ]
    ranked = rank_candidates("NVDA breakout", hits)
    assert ranked[0]["video_id"] == "cccccccccc3"   # exact match scores highest
    assert ranked[-1]["video_id"] == "aaaaaaaaaa1"  # unrelated last
    assert all("match" in r for r in ranked)
    assert ranked[0]["match"] >= ranked[1]["match"] >= ranked[2]["match"]


def test_rank_uses_title_only_part_of_title_dash_channel():
    # the VLM read includes the channel; the actual YT title does not — title-only split wins
    hits = [_hit("dddddddddd4", "How I built a trading bot in Python")]
    ranked = rank_candidates("How I built a trading bot in Python - Coding Channel", hits)
    assert ranked[0]["match"] > 0.8


def test_rank_respects_limit():
    hits = [_hit(f"vid{i:08d}", f"title {i}") for i in range(10)]
    assert len(rank_candidates("title", hits, limit=3)) == 3


def test_channel_split_regex_handles_dash_variants():
    # hyphen, en dash, em dash all split
    for sep in ("-", "–", "—"):
        parts = find_video._CHANNEL_SPLIT.split(f"My Title {sep} My Channel")
        assert parts[0] == "My Title"
