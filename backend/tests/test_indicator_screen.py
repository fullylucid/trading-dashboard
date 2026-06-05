"""Tests for the multi-symbol screener — fan-out + matching + sort, hermetic via a
monkeypatched per-symbol bar fetch."""

import pytest

import indicator_screen as scr
from indicator_spec import SpecError


def _price_spec():
    return {
        "name": "Price",
        "steps": [{"id": "c", "op": "series", "ref": "close"}],
        "plots": [{"step": "c", "label": "Close"}],
    }


def _bars(closes):
    return [{"timestamp": 1000 + i * 86400, "open": c, "high": c, "low": c, "close": c, "volume": 1}
            for i, c in enumerate(closes)]


@pytest.fixture(autouse=True)
def fake_bars(monkeypatch):
    data = {
        "AAPL": _bars([140, 145, 150]),  # last 150
        "MSFT": _bars([95, 92, 90]),     # last 90
        "TSLA": [],                       # no data
    }
    monkeypatch.setattr(scr, "_bars_for", lambda sym, days=400: data.get(sym, []))


def test_screen_matches_and_sorts():
    res = scr.screen(["aapl", "msft", "tsla"], _price_spec(), "c", "gt", 100)
    by = {r["symbol"]: r for r in res}
    assert by["AAPL"]["matched"] is True and by["AAPL"]["value"] == 150
    assert by["MSFT"]["matched"] is False and by["MSFT"]["value"] == 90
    assert by["TSLA"]["matched"] is False and by["TSLA"]["error"] == "no data"
    # matches sort first
    assert res[0]["symbol"] == "AAPL"


def test_screen_dedups_and_uppercases():
    res = scr.screen(["aapl", "AAPL", " msft "], _price_spec(), "c", "gt", 100)
    syms = [r["symbol"] for r in res]
    assert syms.count("AAPL") == 1 and "MSFT" in syms


def test_screen_rejects_bad_input():
    with pytest.raises(ValueError):
        scr.screen(["AAPL"], _price_spec(), "c", "nope", 100)
    with pytest.raises(ValueError):
        scr.screen(["AAPL"], _price_spec(), "missing", "gt", 100)
    with pytest.raises(SpecError):
        scr.screen(["AAPL"], {"name": "x"}, "c", "gt", 100)
