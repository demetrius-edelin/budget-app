"""Calendar periods: day, week (Monday to Sunday) and month."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

KINDS = ("day", "week", "month")
WEEKDAYS = ("lun", "mar", "mie", "joi", "vin", "sâm", "dum")
MONTHS = ("ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec")
MONTH_NAMES = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
)


def short_date(day: date) -> str:
    """Return a short Romanian date, for example 'mar 29 sep'."""
    return f"{WEEKDAYS[day.weekday()]} {day.day:02d} {MONTHS[day.month - 1]}"


def month_short(day: date) -> str:
    """Return the month and the two-digit year, for example 'sep 26'."""
    return f"{MONTHS[day.month - 1]} {day.year % 100:02d}"


@dataclass(frozen=True)
class Period:
    kind: str
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def period_for(kind: str, anchor: date) -> Period:
    """Return the full period of the given kind that holds the anchor date."""
    if kind == "day":
        return Period("day", anchor, anchor)
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return Period("week", start, start + timedelta(days=6))
    if kind == "month":
        start = anchor.replace(day=1)
        last = calendar.monthrange(anchor.year, anchor.month)[1]
        return Period("month", start, anchor.replace(day=last))
    raise ValueError(f"Unknown period kind: {kind!r}")


def previous_period(period: Period) -> Period:
    """Return the period of the same kind that ends right before this one."""
    return period_for(period.kind, period.start - timedelta(days=1))


def next_period(period: Period) -> Period:
    return period_for(period.kind, period.end + timedelta(days=1))


def to_date(period: Period, today: date) -> Period:
    """Clamp the period to today. A future period keeps only its first day."""
    end = max(period.start, min(period.end, today))
    return Period(period.kind, period.start, end)


def same_span_previous(period: Period, today: date) -> Period:
    """Return the same elapsed span in the previous period.

    For a complete period, return the whole previous period.
    """
    current = to_date(period, today)
    previous = previous_period(period)
    if current.end >= period.end:
        return previous
    end = min(previous.start + timedelta(days=current.days - 1), previous.end)
    return Period(period.kind, previous.start, end)


def shift_periods(period: Period, count: int) -> Period:
    """Move the period by count steps. A negative count moves backward."""
    result = period
    step = next_period if count > 0 else previous_period
    for _ in range(abs(count)):
        result = step(result)
    return result


def period_label(period: Period) -> str:
    """Return a short Romanian label, for example 'Săptămâna 21–27 sep 2026'."""
    if period.kind == "day":
        return f"{short_date(period.start)} {period.start.year}"
    if period.kind == "week":
        end = period.end
        if period.start.month == end.month:
            return f"Săptămâna {period.start.day}–{end.day} {MONTHS[end.month - 1]} {end.year}"
        start = period.start
        return (
            f"Săptămâna {start.day:02d} {MONTHS[start.month - 1]}–"
            f"{end.day:02d} {MONTHS[end.month - 1]} {end.year}"
        )
    return f"{MONTH_NAMES[period.start.month - 1]} {period.start.year}"
