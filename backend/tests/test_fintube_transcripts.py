"""Unit tests for fintube.transcripts._parse_vtt — VTT caption cleanup.

YouTube auto-captions are noisy: a WEBVTT header, cue-timing lines, inline <c>/<00:..>
tags, cue-position artifacts, and heavy rolling-caption duplication. _parse_vtt has to
strip all of that down to clean, de-duplicated prose.
"""

from fintube.transcripts import _parse_vtt


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
