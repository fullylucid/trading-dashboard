"""Unit tests for fintube.tickers — the per-ticker intelligence rollup.

Feed, leaderboard track record, and price history are all mocked (no network), so the
aggregation is pinned: crowd counts/lean, distinct-creator stance + track record, the
smart-money agree/fade read, live price + return since first call, avg target/upside,
and the derived signal label.
"""

import datetime as dt

import pandas as pd
import pytest

from fintube import scoring, tickers
from fintube.tickers import _signal


TODAY = dt.date(2026, 6, 10)


def _frame(points):
    idx = pd.to_datetime([p[0] for p in points])
    return pd.DataFrame({"Close": [float(p[1]) for p in points]}, index=idx)


_PRICES = {
    "NVDA": _frame([("2026-01-01", 200), ("2026-06-10", 260)]),  # +30% since first call
    "TSLA": _frame([("2026-02-01", 400), ("2026-06-10", 380)]),
}

# Alpha is the sharp creator (high α track record); ZipTrader is unproven (scored 0).
_BOARD = [
    {"channel": "Alpha", "avg_alpha": 0.20, "hit_rate": 0.8, "scored": 10},
    {"channel": "Crowd1", "avg_alpha": -0.05, "hit_rate": 0.4, "scored": 5},
    {"channel": "Crowd2", "avg_alpha": -0.02, "hit_rate": 0.45, "scored": 4},
    {"channel": "ZipTrader", "avg_alpha": None, "hit_rate": None, "scored": 0},
]

_FEED = [
    # NVDA: crowd is long (3 buys) but the sharp creator (Alpha) is SHORT -> contrarian
    {"category": "finance", "channel": "Crowd1", "published": "2026-01-01", "video_id": "n1",
     "title": "NVDA to the moon", "url": "u1",
     "distill": {"calls": [{"ticker": "NVDA", "action": "buy", "conviction": "high",
                            "horizon": "weeks", "price_target": 300, "thesis": "AI"}]}},
    {"category": "finance", "channel": "Crowd2", "published": "2026-02-01", "video_id": "n2",
     "title": "NVDA breakout", "url": "u2",
     "distill": {"calls": [{"ticker": "NVDA", "action": "buy", "conviction": "medium",
                            "horizon": "days", "price_target": 320}]}},
    {"category": "finance", "channel": "ZipTrader", "published": "2026-03-01", "video_id": "n3",
     "title": "NVDA buy now", "url": "u3",
     "distill": {"calls": [{"ticker": "NVDA", "action": "buy"}]}},
    {"category": "finance", "channel": "Alpha", "published": "2026-03-15", "video_id": "n4",
     "title": "NVDA is toppy", "url": "u4",
     "distill": {"calls": [{"ticker": "NVDA", "action": "sell", "conviction": "high"}]}},
    # TSLA: single watch-only call -> watchlist, no directional lean
    {"category": "finance", "channel": "Crowd1", "published": "2026-02-01", "video_id": "t1",
     "title": "TSLA on radar", "url": "u5",
     "distill": {"calls": [{"ticker": "TSLA", "action": "watch"}]}},
    # noise that must be ignored
    {"category": "ai-coding", "channel": "X", "published": "2026-01-01", "video_id": "z1",
     "distill": {"calls": [{"ticker": "GOOG", "action": "buy"}]}},
]


@pytest.fixture
def intel(monkeypatch):
    monkeypatch.setattr(tickers.store, "r", lambda: None)
    monkeypatch.setattr(tickers.store, "get_feed", lambda limit=400: list(_FEED))
    monkeypatch.setattr(scoring, "compute_leaderboard",
                        lambda force=False, today=None: {"leaderboard": _BOARD})
    monkeypatch.setattr(tickers.scoring, "_hist",
                        lambda tk, start, today=None: _PRICES.get(tk))
    out = tickers.compute_ticker_intel(force=True, today=TODAY)
    return {t["ticker"]: t for t in out["tickers"]}, out


def test_only_finance_tickers_rolled_up(intel):
    rows, _ = intel
    assert set(rows) == {"NVDA", "TSLA"}  # GOOG (ai-coding) excluded


def test_nvda_crowd_counts_and_lean(intel):
    nvda = intel[0]["NVDA"]
    assert nvda["mentions"] == 4
    assert nvda["buy"] == 3
    assert nvda["sell"] == 1
    assert nvda["crowd_lean"] == pytest.approx((3 - 1) / 4)  # +0.5
    assert nvda["net"] == "bullish"


def test_nvda_contrarian_signal(intel):
    # crowd is long, but the only directional creator with a track record (Alpha) is short
    nvda = intel[0]["NVDA"]
    assert nvda["top_creator"] == "Alpha"
    assert nvda["smart_agrees"] is False
    assert "contrarian" in nvda["signal"]


def test_creators_ranked_by_track_record(intel):
    nvda = intel[0]["NVDA"]
    # Alpha (α 0.20) ranks first; ZipTrader (unscored) ranks last
    assert nvda["creators"][0]["channel"] == "Alpha"
    assert nvda["creators"][-1]["channel"] == "ZipTrader"


def test_nvda_price_and_return(intel):
    nvda = intel[0]["NVDA"]
    assert nvda["price"] == 260.0
    assert nvda["ret_since_first"] == pytest.approx(0.30, abs=1e-4)  # 200 -> 260 since 2026-01-01


def test_nvda_avg_target_and_upside(intel):
    nvda = intel[0]["NVDA"]
    assert nvda["avg_price_target"] == pytest.approx(310.0)          # mean(300, 320)
    assert nvda["upside"] == pytest.approx(310 / 260 - 1, abs=1e-4)


def test_tsla_watchlist_only(intel):
    tsla = intel[0]["TSLA"]
    assert tsla["buy"] == 0 and tsla["sell"] == 0
    assert tsla["watch"] == 1
    assert tsla["signal"] == "watchlist"
    assert tsla["smart_agrees"] is None


def test_ranking_most_mentioned_first(intel):
    _, out = intel
    assert [t["ticker"] for t in out["tickers"]] == ["NVDA", "TSLA"]


def test_calls_attach_creator_track_record(intel):
    nvda = intel[0]["NVDA"]
    by_ch = {c["channel"]: c for c in nvda["calls"]}
    assert by_ch["Alpha"]["creator_alpha"] == 0.20
    assert by_ch["ZipTrader"]["creator_alpha"] is None


# --------------------------------------------------------------------------- #
# _signal label logic
# --------------------------------------------------------------------------- #
def test_signal_watchlist_when_no_directional():
    assert _signal(mentions=2, crowd_lean=0.0, smart_agrees=None, directional=0) == "watchlist"


def test_signal_contrarian_overrides_consensus():
    assert "contrarian" in _signal(3, 0.8, smart_agrees=False, directional=3)


def test_signal_consensus_when_one_sided_and_smart_agrees():
    assert _signal(4, 0.75, smart_agrees=True, directional=4) == "consensus long"
    assert _signal(4, -0.75, smart_agrees=None, directional=4) == "consensus short"


def test_signal_single_and_leaning():
    assert _signal(1, 1.0, None, 1) == "single long call"
    assert _signal(3, 0.33, None, 3) == "leaning long"
