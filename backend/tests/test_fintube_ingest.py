"""Unit tests for fintube.ingest URL classification (parse_target).

parse_target is the front door for everything a user pastes — a wrong classification
sends a video down the channel path (or vice versa), so pin every branch.
"""

import pytest

from fintube.ingest import parse_target


@pytest.mark.parametrize("url, expected_id", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),  # bare 11-char id
])
def test_parse_target_video(url, expected_id):
    assert parse_target(url) == ("video", expected_id)


@pytest.mark.parametrize("url, expected_ident", [
    ("https://www.youtube.com/channel/UCJtfma0mE_XrBAD9uakcjfA", "UCJtfma0mE_XrBAD9uakcjfA"),
    ("https://www.youtube.com/channel/UCJtfma0mE_XrBAD9uakcjfA/videos", "UCJtfma0mE_XrBAD9uakcjfA"),
    ("https://www.youtube.com/@grahamstephan", "@grahamstephan"),
    ("https://www.youtube.com/@graham.stephan/videos", "@graham.stephan"),
    ("@meetkevin", "@meetkevin"),
    ("UCJtfma0mE_XrBAD9uakcjfA", "UCJtfma0mE_XrBAD9uakcjfA"),  # bare channel id (>20, UC)
])
def test_parse_target_channel(url, expected_ident):
    assert parse_target(url) == ("channel", expected_ident)


def test_parse_target_video_takes_priority_over_channel():
    # a watch URL that also carries a channel handle in the query must still read as a video
    kind, ident = parse_target("https://www.youtube.com/watch?v=abcdefghijk&ab_channel=@foo")
    assert kind == "video"
    assert ident == "abcdefghijk"


@pytest.mark.parametrize("url", [
    "not a url",
    "https://example.com/something",
    "UCtooShort",          # starts UC but not long enough
    "",
])
def test_parse_target_unknown(url):
    kind, ident = parse_target(url)
    assert kind == "unknown"
    assert ident == url.strip()


def test_parse_target_strips_whitespace():
    assert parse_target("  dQw4w9WgXcQ  ") == ("video", "dQw4w9WgXcQ")
