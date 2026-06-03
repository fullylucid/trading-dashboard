"""PURE tests for the LLM assessment helpers (``sector_rotation.assessment``).

No network / no worker. Exercises the prompt-payload distillation and the
tolerant response parser; the async :func:`generate_assessment` is not invoked
here (it needs the agent bus).
"""

from sector_rotation.assessment import (
    _derive_short,
    _parse_response,
    build_payload,
)


def _sample_result():
    return {
        "rotation": {
            "Information Technology": {
                "sector": "Information Technology",
                "etf": "XLK",
                "status": "rotating-IN",
                "rotation_score": 45.0,
                "confidence": 82.0,
                "phase": "Leading",
                "components": {"market": 50.0, "media": 12.0, "catalyst": None},
            },
            "Utilities": {
                "sector": "Utilities",
                "etf": "XLU",
                "status": "rotating-OUT",
                "rotation_score": -30.0,
                "confidence": 70.0,
                "phase": "Lagging",
                "components": {"market": -40.0},
            },
        },
        "summary": {"rotating_in": [1], "rotating_out": [1], "alerts": []},
        "companies": {"tailwinds": ["AAPL", "NVDA"], "risks": ["DUK"]},
        "market": {"benchmark": "SPY"},
        "sources_ok": {"market": True, "media": True},
    }


def _sample_contrib():
    return {
        "by_etf": {
            "XLK": {
                "breadth": 0.7,
                "leaders_up": [
                    {
                        "symbol": "NVDA",
                        "pct_change": 3.1,
                        "contribution": 0.46,
                        "in_portfolio": True,
                        "news": {"label": "positive", "top_headline": "Nvidia raises guidance"},
                    }
                ],
                "leaders_down": [],
            }
        }
    }


def test_build_payload_orders_by_abs_score_and_names_drivers():
    payload = build_payload(_sample_result(), _sample_contrib())
    assert payload["benchmark"] == "SPY"
    assert payload["headline_counts"]["rotating_in"] == 1
    # Highest |score| first: XLK (45) before XLU (30).
    assert payload["sectors"][0]["etf"] == "XLK"
    xlk = payload["sectors"][0]
    assert xlk["leaders_up"][0]["symbol"] == "NVDA"
    assert xlk["leaders_up"][0]["held"] is True
    assert xlk["leaders_up"][0]["news"]["tone"] == "positive"
    # None-valued drivers are dropped from the compacted payload.
    assert "catalyst" not in xlk["drivers"]
    assert payload["portfolio"]["tailwinds"] == ["AAPL", "NVDA"]


def test_build_payload_without_contributors():
    payload = build_payload(_sample_result(), None)
    assert payload["sectors"][0]["etf"] == "XLK"
    assert "leaders_up" not in payload["sectors"][0]  # no contrib block merged


def test_parse_response_strict_json():
    out = _parse_response('{"short":"a","full":"b"}')
    assert out == {"short": "a", "full": "b"}


def test_parse_response_fenced_json():
    raw = 'sure:\n```json\n{"short": "x", "full": "y"}\n```\nhope that helps'
    assert _parse_response(raw) == {"short": "x", "full": "y"}


def test_parse_response_prose_fallback():
    out = _parse_response("Tech is leading. Nvidia pulled it up 3%. Energy lagged.")
    assert out is not None
    assert out["full"].startswith("Tech is leading")
    assert out["short"]  # derived, non-empty


def test_parse_response_short_only_derives_full():
    out = _parse_response('{"short": "just the tldr"}')
    assert out == {"short": "just the tldr", "full": "just the tldr"}


def test_parse_response_empty_is_none():
    assert _parse_response("") is None
    assert _parse_response(None) is None
    assert _parse_response("   ") is None


def test_derive_short_strips_markdown_and_truncates():
    long = "# Heading\n\n" + "Sector rotation is broad today. " * 40
    short = _derive_short(long)
    assert "#" not in short
    assert len(short) <= 326  # 320 budget + ellipsis
