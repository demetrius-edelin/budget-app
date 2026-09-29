from datetime import date

from spendtrack.core.periods import (
    month_short,
    period_for,
    period_label,
    previous_period,
    same_span_previous,
    to_date,
)

TODAY = date(2026, 9, 29)


def test_week_starts_on_monday() -> None:
    week = period_for("week", TODAY)
    assert week.start == date(2026, 9, 28)
    assert week.end == date(2026, 10, 4)


def test_month_bounds() -> None:
    month = period_for("month", TODAY)
    assert (month.start, month.end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert previous_period(month).start == date(2026, 8, 1)


def test_same_span_previous_for_a_week_in_progress() -> None:
    week = period_for("week", TODAY)
    assert to_date(week, TODAY).days == 2
    span = same_span_previous(week, TODAY)
    assert (span.start, span.end) == (date(2026, 9, 21), date(2026, 9, 22))


def test_same_span_previous_for_a_complete_week() -> None:
    week = period_for("week", date(2026, 9, 21))
    span = same_span_previous(week, TODAY)
    assert (span.start, span.end) == (date(2026, 9, 14), date(2026, 9, 20))


def test_same_span_previous_for_a_month_in_progress() -> None:
    month = period_for("month", TODAY)
    span = same_span_previous(month, TODAY)
    assert (span.start, span.end) == (date(2026, 8, 1), date(2026, 8, 29))


def test_labels() -> None:
    assert period_label(period_for("week", date(2026, 9, 21))) == "Săptămâna 21–27 sep 2026"
    assert period_label(period_for("day", TODAY)) == "mar 29 sep 2026"
    assert period_label(period_for("month", TODAY)) == "septembrie 2026"


def test_month_short_spells_the_year() -> None:
    assert month_short(date(2025, 10, 1)) == "oct 2025"
    assert month_short(TODAY) == "sep 2026"
