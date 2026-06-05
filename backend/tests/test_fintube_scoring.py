"""Unit tests for fintube.scoring — forward-return alpha leaderboard.

Price history is mocked (no network / yfinance), so the math is pinned to hand-computed
values: signed return by direction, alpha vs SPY, hit rate, call-vs-scored counts, and
the filtering of non-finance docs, undated docs, invalid tickers, and non-directional calls.
"""

import pandas as pd
import pytest

from fintube import scoring


def _frame(start_close, end_close, start="2026-01-01", end="2026-06-01"):
    idx = pd.to_datetime([start, end])
    return pd.DataFrame({"Close": [float(start_close), float(end_close)]}, index=idx)


# Hand-computed scenario:
#   SPY  100 -> 110   => benchmark return 0.10
#   NVDA 200 -> 260   => +0.30 ; Alpha BUY  -> signed 0.30, alpha 0.30-0.10 = 0.20
#   TSLA 400 -> 320   => -0.20 ; Beta  SELL -> signed 0.20, alpha 0.20-(-0.10) = 0.30
#   AMD  -> no price  => counted as a call but not scored
_PRICES = {
    "SPY": _frame(100, 110),
    "NVDA": _frame(200, 260),
    "TSLA": _frame(400, 320),
    "AMD": None,
}

_FEED = [
    {"category": "finance", "channel": "Alpha", "published": "2026-01-01",
     "video_id": "v1", "title": "Alpha picks",
     "distill": {"calls": [
         {"ticker": "NVDA", "action": "buy"},
         {"ticker": "AMD", "action": "buy"},          # no price -> unscored
         {"ticker": "BADTICKER123", "action": "buy"}, # invalid symbol -> filtered
         {"ticker": "MSFT", "action": "hold"},        # non-directional -> filtered
     ]}},
    {"category": "finance", "channel": "Beta", "published": "2026-01-01",
     "video_id": "v2", "title": "Beta fade",
     "distill": {"calls": [{"ticker": "TSLA", "action": "sell"}]}},
    {"category": "ai-coding", "channel": "NotFinance", "published": "2026-01-01",
     "video_id": "v3", "title": "irrelevant",
     "distill": {"calls": [{"ticker": "GOOG", "action": "buy"}]}},  # non-finance -> skipped
    {"category": "finance", "channel": "Undated", "published": "",
     "video_id": "v4", "title": "no date",
     "distill": {"calls": [{"ticker": "META", "action": "buy"}]}},  # no pub -> skipped
]


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(scoring.store, "r", lambda: None)  # bypass redis cache
    monkeypatch.setattr(scoring.store, "get_feed", lambda limit=400: list(_FEED))
    monkeypatch.setattr(scoring, "_hist", lambda tk, start: _PRICES.get(tk))
    out = scoring.compute_leaderboard(force=True)
    return {row["channel"]: row for row in out["leaderboard"]}, out


def test_only_finance_dated_channels_present(board):
    rows, _ = board
    assert set(rows) == {"Alpha", "Beta"}


def test_alpha_channel_counts(board):
    rows, _ = board
    a = rows["Alpha"]
    assert a["calls"] == 2          # NVDA + AMD (bad ticker & hold filtered pre-count)
    assert a["scored"] == 1         # only NVDA had prices
    assert a["avg_alpha"] == pytest.approx(0.20, abs=1e-6)
    assert a["hit_rate"] == 1.0


def test_sell_call_scored_with_sign_flip(board):
    rows, _ = board
    b = rows["Beta"]
    assert b["calls"] == 1
    assert b["scored"] == 1
    # SELL on a -20% mover beats a +10% benchmark -> strong positive alpha
    assert b["avg_alpha"] == pytest.approx(0.30, abs=1e-6)
    assert b["hit_rate"] == 1.0


def test_board_sorted_by_avg_alpha_desc(board):
    _, out = board
    channels = [row["channel"] for row in out["leaderboard"]]
    assert channels == ["Beta", "Alpha"]


def test_picks_carry_signed_return_and_alpha(board):
    rows, _ = board
    pick = rows["Alpha"]["picks"][0]
    assert pick["ticker"] == "NVDA"
    assert pick["ret"] == pytest.approx(0.30, abs=1e-4)
    assert pick["alpha"] == pytest.approx(0.20, abs=1e-4)


def test_empty_feed_yields_empty_board(monkeypatch):
    monkeypatch.setattr(scoring.store, "r", lambda: None)
    monkeypatch.setattr(scoring.store, "get_feed", lambda limit=400: [])
    out = scoring.compute_leaderboard(force=True)
    assert out["leaderboard"] == []
    assert "generated" in out
