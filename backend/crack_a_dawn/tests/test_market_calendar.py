"""Validate the NYSE calendar against known dates."""
import datetime as dt

from crack_a_dawn.market_calendar import is_trading_day, market_holidays


def test_known_2026_holidays():
    h = market_holidays(2026)
    expected = {
        dt.date(2026, 1, 1),    # New Year's
        dt.date(2026, 1, 19),   # MLK
        dt.date(2026, 2, 16),   # Presidents'
        dt.date(2026, 4, 3),    # Good Friday (Easter Apr 5)
        dt.date(2026, 5, 25),   # Memorial
        dt.date(2026, 6, 19),   # Juneteenth
        dt.date(2026, 7, 3),    # Independence observed (Jul 4 is Sat)
        dt.date(2026, 9, 7),    # Labor
        dt.date(2026, 11, 26),  # Thanksgiving
        dt.date(2026, 12, 25),  # Christmas
    }
    assert expected <= h


def test_weekend_and_holiday_not_trading():
    assert not is_trading_day(dt.date(2026, 5, 30))   # Saturday
    assert not is_trading_day(dt.date(2026, 5, 31))   # Sunday
    assert not is_trading_day(dt.date(2026, 12, 25))  # Christmas (Fri)
    assert not is_trading_day(dt.date(2026, 7, 3))    # Independence observed (Fri)


def test_normal_weekday_is_trading():
    assert is_trading_day(dt.date(2026, 6, 1))    # Monday, no holiday
    assert is_trading_day(dt.date(2026, 12, 24))  # Thu, normal session (Christmas Eve early-close not modeled)
