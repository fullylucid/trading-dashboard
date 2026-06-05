"""Unit tests for fintube.distill — JSON extraction from model output and prompt selection.

_extract_json is the trust boundary between the LLM and the feed: it must recover JSON
from fenced/prose-wrapped output and reject garbage rather than persisting half-parsed
junk. build_prompt picks the schema the model is graded against, so verify mode routing.
"""

from fintube import distill
from fintube.distill import _extract_json, build_prompt


# --------------------------------------------------------------------------- #
# _extract_json
# --------------------------------------------------------------------------- #
def test_extract_plain_json():
    assert _extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_extract_strips_json_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_strips_bare_fence():
    assert _extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_from_surrounding_prose():
    # model prepends prose despite instructions — recover the object anyway
    out = _extract_json('Here is the JSON you asked for:\n{"ticker": "NVDA"}\nHope that helps!')
    assert out == {"ticker": "NVDA"}


def test_extract_nested_uses_outermost_braces():
    out = _extract_json('prefix {"calls": [{"ticker": "AAPL"}], "n": 1} suffix')
    assert out == {"calls": [{"ticker": "AAPL"}], "n": 1}


def test_extract_empty_returns_none():
    assert _extract_json("") is None
    assert _extract_json(None) is None  # type: ignore[arg-type]


def test_extract_no_braces_returns_none():
    assert _extract_json("no json here at all") is None


def test_extract_malformed_returns_none():
    # has braces but isn't valid JSON (single quotes / unquoted keys)
    assert _extract_json("{bad: 'json'}") is None


# --------------------------------------------------------------------------- #
# build_prompt
# --------------------------------------------------------------------------- #
def test_build_prompt_finance_schema():
    p = build_prompt("transcript text", "Title", "Channel", "finance")
    assert '"calls"' in p
    assert "creator_view" in p
    assert "research scout" not in p


def test_build_prompt_general_schema_interpolates_category():
    p = build_prompt("transcript text", "Title", "Channel", "ai-coding")
    assert "key_insights" in p
    assert '"category":"ai-coding"' in p
    assert '"calls"' not in p  # general schema has no calls array


def test_build_prompt_discovery_mode_overrides_category():
    # discovery mode applies even for a finance category — it's about vetting, not calls
    p = build_prompt("transcript", "Title", "Channel", "finance", mode="discovery")
    assert "research scout" in p
    assert "relevance" in p
    assert "worth_sharing" in p


def test_build_prompt_truncates_long_transcript():
    long = "x" * (distill.MAX_CHARS + 5000)
    p = build_prompt(long, "T", "C", "general")
    # transcript is capped at MAX_CHARS; the prompt is head + metadata + capped body
    assert p.count("x") == distill.MAX_CHARS


def test_build_prompt_includes_metadata():
    p = build_prompt("body", "My Title", "My Channel", "science")
    assert "My Title" in p
    assert "My Channel" in p
    assert "body" in p
