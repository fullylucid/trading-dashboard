"""Unit tests for fintube.scoring — horizon-windowed alpha leaderboard.

Price history is mocked (no network / yfinance) and `today` is injected, so the math is
pinned to hand-computed values: each directional call is scored over [pub, pub+horizon]
(or to-date if still open), alpha = signed return - benchmark, hit = positive alpha,
`watch` is tracked-not-scored, `hold`/invalid tickers/undated/non-finance are dropped.
"""

import datetime as dt

import pandas as pd
import pytest

from fintube import scoring
from fintube.scoring import horizon_to_days


# --------------------------------------------------------------------------- #
# horizon_to_days
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("phrase, expected", [
    ("days", 7),          # bare unit -> sensible default
    ("3 days", 3),
    ("10 days", 10),
    ("weeks", 14),
    ("2 weeks", 14),
    ("1 week", 7),
    ("months", 90),
    ("3 months", 90),
    ("1 month", 30),
    ("1-3yr", 3 * 365),   # range takes the larger bound
    ("2 years", 2 * 365),
    ("1 quarter", 90),
])
def test_horizon_to_days(phrase, expected):
    assert horizon_to_days(phrase) == expected


def test_horizon_defaults_and_caps():
    assert horizon_to_days(None) == scoring._HORIZON_DEFAULT_DAYS
    assert horizon_to_days("") == scoring._HORIZON_DEFAULT_DAYS
    assert horizon_to_days("whenever") == scoring._HORIZON_DEFAULT_DAYS  # unknown unit
    assert horizon_to_days("100 years") == scoring._HORIZON_CAP_DAYS     # capped at 3y


# --------------------------------------------------------------------------- #
# compute_leaderboard — hand-computed windowed scenario
# --------------------------------------------------------------------------- #
TODAY = dt.date(2026, 6, 10)


def _frame(points):
    idx = pd.to_datetime([p[0] for p in points])
    return pd.DataFrame({"Close": [float(p[1]) for p in points]}, index=idx)


# SPY over NVDA window [01-01,01-15]: 100 -> 103 => +0.03
# SPY over Beta window [06-01,06-10]: 110 -> 112 => +0.018181...
_PRICES = {
    "SPY": _frame([("2026-01-01", 100), ("2026-01-15", 103),
                   ("2026-06-01", 110), ("2026-06-10", 112)]),
    # NVDA buy, horizon "weeks" (14d) -> settled window 01-01..01-15: 200->230 = +0.15
    "NVDA": _frame([("2026-01-01", 200), ("2026-01-15", 230), ("2026-06-10", 999)]),
    # GOOG sell, horizon "1-3yr" -> window open, scored to today 06-01..06-10: 400->380 = -0.05
    "GOOG": _frame([("2026-06-01", 400), ("2026-06-10", 380)]),
    "AMD": None,  # no price -> counted but unscored
}

_FEED = [
    {"category": "finance", "channel": "Alpha", "published": "2026-01-01",
     "video_id": "v1", "title": "Alpha picks", "distill": {"calls": [
         {"ticker": "NVDA", "action": "buy", "horizon": "weeks"},
         {"ticker": "AMD", "action": "buy", "horizon": "days"},   # unscored (no price)
         {"ticker": "TSLA", "action": "watch"},                   # tracked, not scored
         {"ticker": "MSFT", "action": "hold"},                    # ignored
         {"ticker": "BAD123", "action": "buy"},                   # invalid symbol -> dropped
     ]}},
    {"category": "finance", "channel": "Beta", "published": "2026-06-01",
     "video_id": "v2", "title": "Beta fade", "distill": {"calls": [
         {"ticker": "GOOG", "action": "sell", "horizon": "1-3yr"}]}},
    {"category": "ai-coding", "channel": "NotFinance", "published": "2026-01-01",
     "video_id": "v3", "title": "x", "distill": {"calls": [
         {"ticker": "META", "action": "buy"}]}},                  # non-finance -> skipped
    {"category": "finance", "channel": "Undated", "published": "",
     "video_id": "v4", "title": "y", "distill": {"calls": [
         {"ticker": "AAPL", "action": "buy"}]}},                  # no date -> skipped
]


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(scoring.store, "r", lambda: None)
    monkeypatch.setattr(scoring.store, "get_feed", lambda limit=400: list(_FEED))
    monkeypatch.setattr(scoring, "_hist", lambda tk, start, today=None: _PRICES.get(tk))
    out = scoring.compute_leaderboard(force=True, today=TODAY)
    return {row["channel"]: row for row in out["leaderboard"]}, out


def test_only_finance_dated_channels_present(board):
    rows, _ = board
    assert set(rows) == {"Alpha", "Beta"}


def test_alpha_channel_windowed(board):
    a = board[0]["Alpha"]
    assert a["calls"] == 2            # NVDA + AMD (watch/hold/bad excluded from calls)
    assert a["scored"] == 1           # only NVDA had prices
    assert a["settled"] == 1          # NVDA's 14d window closed before today
    assert a["in_flight"] == 0
    assert a["watch_calls"] == 1      # TSLA watch tracked separately
    # NVDA +15% over window vs SPY +3% => alpha 0.12
    assert a["avg_alpha"] == pytest.approx(0.12, abs=1e-4)
    assert a["hit_rate"] == 1.0


def test_beta_sell_in_flight(board):
    b = board[0]["Beta"]
    assert b["scored"] == 1
    assert b["settled"] == 0
    assert b["in_flight"] == 1        # 1-3yr horizon still open -> scored to today
    # GOOG -5% over window, SELL => signed +0.05; SPY +1.818% => alpha 0.05+0.01818 = 0.06818
    assert b["avg_alpha"] == pytest.approx(0.0682, abs=1e-3)


def test_hit_rate_is_alpha_based_not_raw_return(board):
    # Beta's SELL made +5% raw AND beat SPY -> positive alpha -> a hit either way,
    # but the win is recorded on alpha>0 (regression guard for the alpha-consistent rule).
    b = board[0]["Beta"]
    assert b["hit_rate"] == 1.0


def test_board_sorted_by_avg_alpha_desc(board):
    _, out = board
    assert [r["channel"] for r in out["leaderboard"]] == ["Alpha", "Beta"]


def test_picks_carry_window_metadata(board):
    pick = board[0]["Alpha"]["picks"][0]
    assert pick["ticker"] == "NVDA"
    assert pick["horizon_days"] == 14
    assert pick["window_end"] == "2026-01-15"
    assert pick["in_flight"] is False
    assert pick["ret"] == pytest.approx(0.15, abs=1e-4)
    assert pick["alpha"] == pytest.approx(0.12, abs=1e-4)


def test_empty_feed_yields_empty_board(monkeypatch):
    monkeypatch.setattr(scoring.store, "r", lambda: None)
    monkeypatch.setattr(scoring.store, "get_feed", lambda limit=400: [])
    out = scoring.compute_leaderboard(force=True, today=TODAY)
    assert out["leaderboard"] == []
    assert "generated" in out


# --------------------------------------------------------------------------- #
# _hist price cache
# --------------------------------------------------------------------------- #
def test_hist_caches_within_day(monkeypatch):
    scoring.clear_price_cache()
    calls = []
    monkeypatch.setattr(scoring, "_fetch_hist",
                        lambda tk, start: calls.append((tk, start)) or _frame([("2026-01-01", 1)]))
    today = dt.date(2026, 6, 10)
    scoring._hist("NVDA", "2026-01-01", today=today)
    scoring._hist("NVDA", "2026-03-01", today=today)  # later start, already covered -> no refetch
    assert calls == [("NVDA", "2026-01-01")]
    scoring.clear_price_cache()


def test_hist_refetches_when_earlier_start_needed(monkeypatch):
    scoring.clear_price_cache()
    calls = []
    monkeypatch.setattr(scoring, "_fetch_hist",
                        lambda tk, start: calls.append((tk, start)) or _frame([("2026-01-01", 1)]))
    today = dt.date(2026, 6, 10)
    scoring._hist("NVDA", "2026-03-01", today=today)
    scoring._hist("NVDA", "2026-01-01", today=today)  # needs earlier data -> refetch from earliest
    assert calls == [("NVDA", "2026-03-01"), ("NVDA", "2026-01-01")]
    scoring.clear_price_cache()
