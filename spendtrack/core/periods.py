"""Calendar periods: day, week (Monday to Sunday) and month."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

KINDS = ("day", "week", "month")


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
    """Return a short label, for example 'Week 21–27 Sep 2026'."""
    if period.kind == "day":
        return period.start.strftime("%a %d %b %Y")
    if period.kind == "week":
        if period.start.month == period.end.month:
            return f"Week {period.start.day}–{period.end.day} {period.end:%b %Y}"
        return f"Week {period.start:%d %b}–{period.end:%d %b %Y}"
    return period.start.strftime("%B %Y")
