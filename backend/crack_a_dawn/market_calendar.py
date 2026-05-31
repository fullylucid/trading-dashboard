"""
US (NYSE) market-calendar helper — dependency-free, valid for any year.

Holiday rules are deterministic, so we compute them rather than pin a library or a
hardcoded year. Covers weekends + the 10 NYSE full-day holidays incl. observed-date
shifts (Sat -> prior Fri, Sun -> next Mon). Does NOT model early-close half-days.
"""
from __future__ import annotations

import datetime as _dt
from typing import Set


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """nth (1-based) weekday (Mon=0) of a month."""
    d = _dt.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + _dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> _dt.date:
    nxt = _dt.date(year + (month == 12), (month % 12) + 1, 1)
    last = nxt - _dt.timedelta(days=1)
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> _dt.date:
    """Anonymous Gregorian computus."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return _dt.date(year, month, day)


def _observed(d: _dt.date) -> _dt.date:
    if d.weekday() == 5:      # Saturday -> Friday
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:      # Sunday -> Monday
        return d + _dt.timedelta(days=1)
    return d


def market_holidays(year: int) -> Set[_dt.date]:
    h = {
        _observed(_dt.date(year, 1, 1)),                 # New Year's Day
        _nth_weekday(year, 1, 0, 3),                     # MLK Jr. (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),                     # Presidents' Day (3rd Mon Feb)
        _easter(year) - _dt.timedelta(days=2),           # Good Friday
        _last_weekday(year, 5, 0),                        # Memorial Day (last Mon May)
        _observed(_dt.date(year, 6, 19)),                # Juneteenth
        _observed(_dt.date(year, 7, 4)),                 # Independence Day
        _nth_weekday(year, 9, 0, 1),                     # Labor Day (1st Mon Sep)
        _nth_weekday(year, 11, 3, 4),                    # Thanksgiving (4th Thu Nov)
        _observed(_dt.date(year, 12, 25)),               # Christmas
    }
    return h


def is_trading_day(d: _dt.date) -> bool:
    """True on weekdays that are not a NYSE full-day holiday."""
    if d.weekday() >= 5:
        return False
    return d not in market_holidays(d.year)
