"""Unit tests for fintube.transcripts._parse_vtt — VTT caption cleanup.

YouTube auto-captions are noisy: a WEBVTT header, cue-timing lines, inline <c>/<00:..>
tags, cue-position artifacts, and heavy rolling-caption duplication. _parse_vtt has to
strip all of that down to clean, de-duplicated prose.
"""

from fintube.transcripts import _parse_vtt, _parse_vtt_timed, _hms_to_s, timed_text


def _write(tmp_path, text):
    p = tmp_path / "sub.en.vtt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parse_basic(tmp_path):
    vtt = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "hello world\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "second line\n"
    )
    assert _parse_vtt(_write(tmp_path, vtt)) == "hello world second line"


def test_parse_dedups_rolling_captions(tmp_path):
    # YouTube repeats the prior cue's text as the next cue scrolls in
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "the quick brown\n"
        "\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "the quick brown\n"
        "\n"
        "00:00:04.000 --> 00:00:06.000\n"
        "fox jumps\n"
    )
    assert _parse_vtt(_write(tmp_path, vtt)) == "the quick brown fox jumps"


def test_parse_strips_inline_tags(tmp_path):
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "<c>styled</c> and <00:00:01.000>timed</c> text\n"
    )
    assert _parse_vtt(_write(tmp_path, vtt)) == "styled and timed text"


def test_parse_skips_cue_position_artifacts(tmp_path):
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "align:start position:0%\n"
        "real content\n"
    )
    assert _parse_vtt(_write(tmp_path, vtt)) == "real content"


def test_parse_skips_note_blocks(tmp_path):
    vtt = (
        "WEBVTT\n\n"
        "NOTE this is a comment\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "kept\n"
    )
    assert _parse_vtt(_write(tmp_path, vtt)) == "kept"


def test_parse_empty_captions_returns_empty_string(tmp_path):
    vtt = "WEBVTT\nKind: captions\nLanguage: en\n"
    assert _parse_vtt(_write(tmp_path, vtt)) == ""


def test_parse_non_consecutive_duplicates_kept(tmp_path):
    # dedup is only for *consecutive* repeats; a phrase recurring later stays
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\nokay\n\n"
        "00:00:02.000 --> 00:00:04.000\nnext\n\n"
        "00:00:04.000 --> 00:00:06.000\nokay\n"
    )
    assert _parse_vtt(_write(tmp_path, vtt)) == "okay next okay"


# --------------------------------------------------------------------------- #
# timed parsing + marker injection
# --------------------------------------------------------------------------- #
def test_hms_to_s():
    assert _hms_to_s("00", "00", "00", "000") == 0.0
    assert _hms_to_s("00", "12", "30", "500") == 750.5
    assert _hms_to_s("01", "00", "00", "000") == 3600.0


def test_parse_vtt_timed_keeps_start_times(tmp_path):
    vtt = (
        "WEBVTT\n\n"
        "00:00:05.000 --> 00:00:08.000\nfirst\n\n"
        "00:02:00.000 --> 00:02:03.000\nsecond\n"
    )
    segs = _parse_vtt_timed(_write(tmp_path, vtt))
    assert segs == [(5.0, "first"), (120.0, "second")]


def test_timed_text_injects_mmss_markers():
    segs = [(0.0, "intro"), (35.0, "midpoint"), (95.0, "later")]
    out = timed_text(segs, every=30)
    # markers appear at 0,30,60,90 boundaries as each is crossed, before the text
    assert "[00:00] intro" in out
    assert "[00:30]" in out and "midpoint" in out
    assert "[01:30]" in out and "later" in out
    # the 95s segment should have crossed the 60s and 90s marks too
    assert "[01:00]" in out
