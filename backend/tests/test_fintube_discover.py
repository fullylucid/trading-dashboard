"""Unit tests for fintube.discover — row parsing, freshness/duration filtering, merge.

Discovery decides which unvetted search hits are even worth a transcript+distill, so its
filters (date cutoff, Shorts/VOD duration bounds, dedup across queries) are load-bearing.
"""

import datetime as dt

import pytest

from fintube import discover
from fintube.discover import _parse_row, search_recent


def _row(vid="abcdefghijk", ud="20260601", dur="600", views="1000",
         cid="UCxxxxxxxxxxxxxxxxxxxxxx", channel="Chan", title="A Title"):
    return "\t".join([vid, ud, dur, views, cid, channel, title])


# --------------------------------------------------------------------------- #
# _parse_row
# --------------------------------------------------------------------------- #
def test_parse_row_valid():
    c = _parse_row(_row())
    assert c["video_id"] == "abcdefghijk"
    assert c["published"] == "2026-06-01"
    assert c["duration_s"] == 600
    assert c["view_count"] == 1000
    assert c["url"] == "https://www.youtube.com/watch?v=abcdefghijk"


def test_parse_row_too_few_fields():
    assert _parse_row("a\tb\tc") is None


def test_parse_row_bad_video_id():
    assert _parse_row(_row(vid="short")) is None


def test_parse_row_missing_upload_date():
    c = _parse_row(_row(ud="NA"))
    assert c["published"] == ""  # unknown date -> empty, gets dropped downstream


def test_parse_row_unparseable_numbers_become_none():
    c = _parse_row(_row(dur="NA", views="None"))
    assert c["duration_s"] is None
    assert c["view_count"] is None


# --------------------------------------------------------------------------- #
# search_recent (filtering)
# --------------------------------------------------------------------------- #
@pytest.fixture
def today():
    return dt.date(2026, 6, 10)


def test_search_recent_drops_stale(monkeypatch, today):
    rows = [
        _row(vid="freshvideo1", ud="20260608"),   # 2 days old -> keep
        _row(vid="stalevideo1", ud="20260501"),   # 40 days old -> drop
    ]
    monkeypatch.setattr(discover, "_search_raw", lambda q, n, t: rows)
    out = search_recent("q", lookback_days=10, today=today)
    assert [c["video_id"] for c in out] == ["freshvideo1"]


def test_search_recent_drops_shorts_and_vods(monkeypatch, today):
    rows = [
        _row(vid="goodlength1", ud="20260609", dur="600"),       # keep
        _row(vid="tooshorts11", ud="20260609", dur="60"),        # < MIN -> drop
        _row(vid="toolongvod1", ud="20260609", dur=str(5 * 3600)),  # > MAX -> drop
    ]
    monkeypatch.setattr(discover, "_search_raw", lambda q, n, t: rows)
    out = search_recent("q", lookback_days=10, today=today)
    assert [c["video_id"] for c in out] == ["goodlength1"]


def test_search_recent_drops_undated(monkeypatch, today):
    rows = [_row(vid="datelessv11", ud="NA")]
    monkeypatch.setattr(discover, "_search_raw", lambda q, n, t: rows)
    assert search_recent("q", today=today) == []


def test_search_recent_sorts_newest_first_and_tags_query(monkeypatch, today):
    rows = [
        _row(vid="oldervideo1", ud="20260603"),
        _row(vid="newervideo1", ud="20260609"),
    ]
    monkeypatch.setattr(discover, "_search_raw", lambda q, n, t: rows)
    out = search_recent("my query", lookback_days=30, today=today)
    assert [c["video_id"] for c in out] == ["newervideo1", "oldervideo1"]
    assert all(c["query"] == "my query" for c in out)


# --------------------------------------------------------------------------- #
# discover (merge across topics)
# --------------------------------------------------------------------------- #
def test_discover_dedups_and_accumulates_matched_queries(monkeypatch, today):
    shared = {"video_id": "sharedvid11", "published": "2026-06-09", "title": "t",
              "channel": "c", "channel_id": "UC", "duration_s": 600, "view_count": 1,
              "url": "u"}
    only_a = {**shared, "video_id": "onlyinaaaa1"}

    def fake_search(query, **kw):
        if query == "qa":
            return [dict(shared), dict(only_a)]
        if query == "qb":
            return [dict(shared)]
        return []

    monkeypatch.setattr(discover, "search_recent", fake_search)
    topics = [{"query": "qa", "category": "finance"},
              {"query": "qb", "category": "engineering"}]
    merged = discover.discover(topics, today=today)

    by_id = {c["video_id"]: c for c in merged}
    assert set(by_id) == {"sharedvid11", "onlyinaaaa1"}
    # video found by both queries accumulates both, and keeps first-seen category
    assert by_id["sharedvid11"]["matched_queries"] == ["qa", "qb"]
    assert by_id["sharedvid11"]["category"] == "finance"
    # multi-query hit sorts ahead of single-query hit
    assert merged[0]["video_id"] == "sharedvid11"


def test_discover_skips_disabled_topics(monkeypatch, today):
    called = []

    def fake_search(query, **kw):
        called.append(query)
        return []

    monkeypatch.setattr(discover, "search_recent", fake_search)
    discover.discover([{"query": "on", "enabled": True},
                       {"query": "off", "enabled": False}], today=today)
    assert called == ["on"]
