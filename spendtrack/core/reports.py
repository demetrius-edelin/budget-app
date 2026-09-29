"""Totals, breakdowns and comparisons. See the specification, section 8."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from spendtrack.core import settings as settings_core
from spendtrack.core.expenses import (
    DISCRETIONARY_LEVELS,
    NECESSITY_NAMES,
    Line,
    expense_lines,
    necessity_name,
    unrated_count,
)
from spendtrack.core.periods import Period, period_for, same_span_previous, shift_periods, to_date
from spendtrack.db.models import Expense


@dataclass(frozen=True)
class Bucket:
    key: int | None
    name: str
    amount_minor: int
    count: int


@dataclass
class PeriodReport:
    period: Period
    to_date: Period
    previous_span: Period
    total_minor: int
    previous_total_minor: int
    change_pct: float | None
    four_week_avg_minor: int | None
    change_vs_four_week_pct: float | None
    by_necessity: list[Bucket]
    discretionary_minor: int
    discretionary_share_pct: float | None
    flagged_minor: int
    flagged_count: int
    potential_saving_minor: int
    recurring_minor: int
    by_category: list[Bucket]
    daily_average_minor: int
    expense_count: int
    lines: list[Line] = field(default_factory=list)


def counted_expenses(session: Session, start: date, end: date) -> list[Expense]:
    """Return the expenses that count in totals: not deleted, not informational, in range."""
    query = (
        select(Expense)
        .options(selectinload(Expense.items))
        .where(
            Expense.deleted_at.is_(None),
            Expense.informational.is_(False),
            Expense.occurred_on >= start,
            Expense.occurred_on <= end,
        )
        .order_by(Expense.occurred_on, Expense.id)
    )
    return list(session.scalars(query).all())


def total_between(session: Session, start: date, end: date) -> int:
    return sum(expense.amount_minor for expense in counted_expenses(session, start, end))


def lines_between(session: Session, start: date, end: date) -> list[Line]:
    lines: list[Line] = []
    for expense in counted_expenses(session, start, end):
        lines.extend(expense_lines(expense))
    return lines


def pct_change(current: int, previous: int) -> float | None:
    """Return the change in percent, or None when the previous value is zero."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def necessity_buckets(lines: list[Line]) -> list[Bucket]:
    amounts: dict[int | None, int] = defaultdict(int)
    counts: dict[int | None, int] = defaultdict(int)
    for line in lines:
        amounts[line.necessity] += line.amount_minor
        counts[line.necessity] += 1
    keys: list[int | None] = [*NECESSITY_NAMES.keys(), None]
    return [Bucket(key, necessity_name(key), amounts[key], counts[key]) for key in keys]


def category_buckets(lines: list[Line]) -> list[Bucket]:
    amounts: dict[int, int] = defaultdict(int)
    counts: dict[int, int] = defaultdict(int)
    names: dict[int, str] = {}
    for line in lines:
        amounts[line.category_id] += line.amount_minor
        counts[line.category_id] += 1
        names[line.category_id] = line.category_name
    buckets = [Bucket(key, names[key], amounts[key], counts[key]) for key in amounts]
    buckets.sort(key=lambda b: (-b.amount_minor, b.name))
    return buckets


def flagged_lines(lines: list[Line]) -> list[Line]:
    """Return the lines with a cheaper alternative, largest saving first."""
    flagged = [line for line in lines if line.cheaper_alt]
    flagged.sort(key=lambda line: (-line.potential_saving_minor, -line.amount_minor))
    return flagged


def recurring_lines(lines: list[Line]) -> list[Line]:
    recurring = [line for line in lines if line.recurring]
    recurring.sort(key=lambda line: (-line.amount_minor, line.description))
    return recurring


def period_report(session: Session, kind: str, anchor: date, today: date) -> PeriodReport:
    """Build the report of one period, to date."""
    period = period_for(kind, anchor)
    current = to_date(period, today)
    previous_span = same_span_previous(period, today)
    expenses = counted_expenses(session, current.start, current.end)
    lines: list[Line] = []
    for expense in expenses:
        lines.extend(expense_lines(expense))
    total = sum(expense.amount_minor for expense in expenses)
    previous_total = total_between(session, previous_span.start, previous_span.end)

    four_week_avg: int | None = None
    change_vs_four: float | None = None
    if kind == "week":
        totals: list[int] = []
        for back in range(1, 5):
            earlier = shift_periods(period, -back)
            span_end = earlier.start + timedelta(days=current.days - 1)
            totals.append(total_between(session, earlier.start, span_end))
        four_week_avg = round(sum(totals) / 4)
        change_vs_four = pct_change(total, four_week_avg)

    by_necessity = necessity_buckets(lines)
    discretionary = sum(b.amount_minor for b in by_necessity if b.key in DISCRETIONARY_LEVELS)
    flagged = flagged_lines(lines)
    recurring = recurring_lines(lines)
    return PeriodReport(
        period=period,
        to_date=current,
        previous_span=previous_span,
        total_minor=total,
        previous_total_minor=previous_total,
        change_pct=pct_change(total, previous_total),
        four_week_avg_minor=four_week_avg,
        change_vs_four_week_pct=change_vs_four,
        by_necessity=by_necessity,
        discretionary_minor=discretionary,
        discretionary_share_pct=round(discretionary / total * 100, 1) if total else None,
        flagged_minor=sum(line.amount_minor for line in flagged),
        flagged_count=len(flagged),
        potential_saving_minor=sum(line.potential_saving_minor for line in flagged),
        recurring_minor=sum(line.amount_minor for line in recurring),
        by_category=category_buckets(lines),
        daily_average_minor=round(total / current.days) if current.days else 0,
        expense_count=len(expenses),
        lines=lines,
    )


@dataclass(frozen=True)
class TrendPoint:
    period: Period
    by_necessity: dict[int | None, int]
    total_minor: int


def necessity_trend(session: Session, today: date, months: int = 12) -> list[TrendPoint]:
    """Return the monthly totals by necessity level for the last months, oldest first."""
    current = period_for("month", today)
    first = shift_periods(current, -(months - 1))
    lines = lines_between(session, first.start, current.end)
    points: list[TrendPoint] = []
    month = first
    for _ in range(months):
        in_month = [line for line in lines if month.contains(line.occurred_on)]
        amounts: dict[int | None, int] = {key: 0 for key in [*NECESSITY_NAMES.keys(), None]}
        for line in in_month:
            amounts[line.necessity] += line.amount_minor
        points.append(TrendPoint(month, amounts, sum(amounts.values())))
        month = shift_periods(month, 1)
    return points


@dataclass(frozen=True)
class CategoryRow:
    name: str
    amounts: list[int]
    total_minor: int


@dataclass(frozen=True)
class CategoryTable:
    months: list[Period]
    rows: list[CategoryRow]
    totals: list[int]


def category_by_month(session: Session, today: date, months: int = 12) -> CategoryTable:
    """Return a category-by-month table for the last months, largest category first."""
    current = period_for("month", today)
    first = shift_periods(current, -(months - 1))
    lines = lines_between(session, first.start, current.end)
    month_periods: list[Period] = []
    month = first
    for _ in range(months):
        month_periods.append(month)
        month = shift_periods(month, 1)
    per_category: dict[str, list[int]] = defaultdict(lambda: [0] * months)
    for line in lines:
        for index, period in enumerate(month_periods):
            if period.contains(line.occurred_on):
                per_category[line.category_name][index] += line.amount_minor
                break
    rows = [CategoryRow(name, amounts, sum(amounts)) for name, amounts in per_category.items()]
    rows.sort(key=lambda row: (-row.total_minor, row.name))
    totals = [sum(row.amounts[i] for row in rows) for i in range(months)]
    return CategoryTable(month_periods, rows, totals)


@dataclass
class Overview:
    day: PeriodReport
    week: PeriodReport
    month: PeriodReport
    monthly_target_minor: int | None
    target_share_pct: float | None
    top_categories: list[Bucket]
    unrated: int


def overview(session: Session, today: date) -> Overview:
    """Build the Overview page figures."""
    day = period_report(session, "day", today, today)
    week = period_report(session, "week", today, today)
    month = period_report(session, "month", today, today)
    target = settings_core.monthly_target_minor(session)
    share = round(month.total_minor / target * 100, 1) if target else None
    return Overview(
        day=day,
        week=week,
        month=month,
        monthly_target_minor=target,
        target_share_pct=share,
        top_categories=month.by_category[:5],
        unrated=unrated_count(session),
    )


@dataclass(frozen=True)
class CalendarDay:
    day: date
    in_month: bool
    total_minor: int
    count: int


@dataclass(frozen=True)
class MonthCalendar:
    period: Period
    weeks: list[list[CalendarDay]]
    total_minor: int
    max_day_minor: int


def daily_totals(session: Session, start: date, end: date) -> dict[date, tuple[int, int]]:
    """Return {day: (total_minor, expense count)} for the counted expenses in the range."""
    totals: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for expense in counted_expenses(session, start, end):
        entry = totals[expense.occurred_on]
        entry[0] += expense.amount_minor
        entry[1] += 1
    return {day: (values[0], values[1]) for day, values in totals.items()}


def month_calendar(session: Session, anchor: date) -> MonthCalendar:
    """Build the calendar grid of one month: full weeks from Monday to Sunday."""
    period = period_for("month", anchor)
    first = period.start - timedelta(days=period.start.weekday())
    last = period.end + timedelta(days=6 - period.end.weekday())
    totals = daily_totals(session, first, last)
    weeks: list[list[CalendarDay]] = []
    day = first
    while day <= last:
        week: list[CalendarDay] = []
        for _ in range(7):
            total, count = totals.get(day, (0, 0))
            week.append(CalendarDay(day, period.contains(day), total, count))
            day += timedelta(days=1)
        weeks.append(week)
    in_month = [cell for week in weeks for cell in week if cell.in_month]
    return MonthCalendar(
        period=period,
        weeks=weeks,
        total_minor=sum(cell.total_minor for cell in in_month),
        max_day_minor=max((cell.total_minor for cell in in_month), default=0),
    )
