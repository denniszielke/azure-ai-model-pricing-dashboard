"""
test_date_range.py – Tests for month range calculation in normalize.py.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

import pytest

from src.collect.normalize import get_previous_month_range, parse_month_arg


class TestGetPreviousMonthRange:
    def test_regular_month(self) -> None:
        """March 2024 → February 2024 (Feb 1 – Feb 29, leap year)."""
        start, end = get_previous_month_range(reference=date(2024, 3, 15))
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_january_wraps_to_december(self) -> None:
        """January 2024 → December 2023."""
        start, end = get_previous_month_range(reference=date(2024, 1, 1))
        assert start == date(2023, 12, 1)
        assert end == date(2023, 12, 31)

    def test_first_day_of_month(self) -> None:
        """First day of April → March."""
        start, end = get_previous_month_range(reference=date(2024, 4, 1))
        assert start == date(2024, 3, 1)
        assert end == date(2024, 3, 31)

    def test_last_day_of_month(self) -> None:
        """Last day of April → March."""
        start, end = get_previous_month_range(reference=date(2024, 4, 30))
        assert start == date(2024, 3, 1)
        assert end == date(2024, 3, 31)

    def test_non_leap_february(self) -> None:
        """March 2023 → February 2023 (28 days)."""
        start, end = get_previous_month_range(reference=date(2023, 3, 1))
        assert start == date(2023, 2, 1)
        assert end == date(2023, 2, 28)

    def test_start_lte_end(self) -> None:
        """start must always be <= end."""
        for year in range(2020, 2026):
            for month in range(1, 13):
                start, end = get_previous_month_range(reference=date(year, month, 1))
                assert start <= end


class TestParseMonthArg:
    def test_last(self) -> None:
        """'last' should return the previous calendar month."""
        start, end = parse_month_arg("last")
        today = date.today()
        expected_start, expected_end = get_previous_month_range(today)
        assert start == expected_start
        assert end == expected_end

    def test_specific_month(self) -> None:
        """'2024-06' should return June 2024."""
        start, end = parse_month_arg("2024-06")
        assert start == date(2024, 6, 1)
        assert end == date(2024, 6, 30)

    def test_december(self) -> None:
        """December has 31 days."""
        start, end = parse_month_arg("2024-12")
        assert start == date(2024, 12, 1)
        assert end == date(2024, 12, 31)

    def test_february_leap(self) -> None:
        """February in a leap year has 29 days."""
        start, end = parse_month_arg("2024-02")
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_february_non_leap(self) -> None:
        """February in a non-leap year has 28 days."""
        start, end = parse_month_arg("2023-02")
        assert start == date(2023, 2, 1)
        assert end == date(2023, 2, 28)

    def test_invalid_format(self) -> None:
        """Non-standard formats must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid"):
            parse_month_arg("2024/06")

    def test_invalid_not_year_month(self) -> None:
        with pytest.raises(ValueError):
            parse_month_arg("something-random-here")

    def test_end_day_is_last_day_of_month(self) -> None:
        """End day should always be the last day of the month."""
        for year in (2023, 2024):
            for month in range(1, 13):
                _, last = monthrange(year, month)
                _, end = parse_month_arg(f"{year}-{month:02d}")
                assert end.day == last
