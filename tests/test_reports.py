from datetime import date, timedelta

from sqlalchemy.orm import Session

from spendtrack.core import expenses as core
from spendtrack.core import reports
from spendtrack.core import settings as settings_core
from spendtrack.core.expenses import ItemInput
from tests.conftest import TODAY


def _add(session: Session, category, day: date, minor: int, name: str = "Alimente", **kw):
    return core.create_expense(
        session, occurred_on=day, amount_minor=minor, category_id=category(name), **kw
    )


def test_case_15_week_starts_monday(session: Session, category) -> None:
    _add(session, category, date(2026, 9, 29), 10000)
    _add(session, category, date(2026, 9, 28), 3500)
    _add(session, category, date(2026, 9, 27), 5000)
    report = reports.period_report(session, "week", TODAY, TODAY)
    assert report.total_minor == 13500
    assert report.expense_count == 2


def test_case_16_change_compares_the_same_span(session: Session, category) -> None:
    _add(session, category, date(2026, 9, 28), 5000)
    _add(session, category, date(2026, 9, 29), 5000)
    _add(session, category, date(2026, 9, 21), 10000)
    _add(session, category, date(2026, 9, 22), 10000)
    _add(session, category, date(2026, 9, 25), 30000)
    report = reports.period_report(session, "week", TODAY, TODAY)
    assert report.total_minor == 10000
    assert report.previous_total_minor == 20000
    assert report.change_pct == -50.0


def test_four_week_average_uses_the_same_span(session: Session, category) -> None:
    _add(session, category, date(2026, 9, 28), 4000)
    for monday in (date(2026, 9, 21), date(2026, 9, 14), date(2026, 9, 7), date(2026, 8, 31)):
        _add(session, category, monday, 2000)
        _add(session, category, monday + timedelta(days=3), 9000)  # a Thursday
    report = reports.period_report(session, "week", TODAY, TODAY)
    assert report.four_week_avg_minor == 2000
    assert report.change_vs_four_week_pct == 100.0


def test_breakdown_example_from_the_specification(session: Session, category) -> None:
    expense = _add(session, category, TODAY, 10000, necessity=1)
    core.add_items(session, expense.id, [ItemInput("Wine", 5000, necessity=3)])
    report = reports.period_report(session, "day", TODAY, TODAY)
    assert report.total_minor == 10000
    by_level = {bucket.name: bucket.amount_minor for bucket in report.by_necessity}
    assert by_level["Esențial"] == 5000
    assert by_level["Util"] == 5000
    assert report.discretionary_minor == 5000
    assert report.discretionary_share_pct == 50.0


def test_flagged_and_savings(session: Session, category) -> None:
    _add(session, category, TODAY, 1850, "Mâncare în oraș", necessity=4, cheaper_alt_minor=800)
    _add(session, category, TODAY, 3000, "Cumpărături", cheaper_alt=True)
    _add(session, category, TODAY, 500, "Alimente", cheaper_alt_minor=900)
    _add(session, category, TODAY, 3000, "Cumpărături", necessity=3, cheaper_alt_minor=2000)
    report = reports.period_report(session, "day", TODAY, TODAY)
    assert report.flagged_count == 4
    assert report.flagged_minor == 8350
    # The Impulse coffee counts in full (18.50), the Util purchase its difference (10.00).
    assert (report.impulse_minor, report.cheaper_saving_minor) == (1850, 1000)
    assert report.potential_saving_minor == 2850
    assert report.radical_saving_minor == 1850 + 3000  # Impulse coffee + Util purchase
    flagged = reports.flagged_lines(report.lines)
    assert flagged[0].potential_saving_minor == 1050


def test_recurring_total_and_daily_average(session: Session, category) -> None:
    _add(session, category, date(2026, 9, 28), 6000, "Abonamente")
    _add(session, category, date(2026, 9, 29), 4000)
    report = reports.period_report(session, "week", TODAY, TODAY)
    assert report.recurring_minor == 6000
    assert report.daily_average_minor == 5000


def test_deleted_and_informational_rows_are_excluded(session: Session, category) -> None:
    kept = _add(session, category, TODAY, 1000)
    gone = _add(session, category, TODAY, 2000)
    core.delete_expense(session, gone.id)
    _add(session, category, TODAY, 4000, informational=True, source="metric")
    assert reports.total_between(session, TODAY, TODAY) == kept.amount_minor


def test_trend_and_category_table(session: Session, category) -> None:
    _add(session, category, date(2026, 8, 15), 1000, "Alimente", necessity=1)
    _add(session, category, date(2026, 9, 15), 2000, "Mâncare în oraș", necessity=3)
    trend = reports.necessity_trend(session, TODAY, months=3)
    assert [point.period.start for point in trend] == [
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
    ]
    assert trend[1].by_necessity[1] == 1000
    assert trend[2].by_necessity[3] == 2000
    table = reports.category_by_month(session, TODAY, months=3)
    assert [row.name for row in table.rows] == ["Mâncare în oraș", "Alimente"]
    assert table.totals == [0, 1000, 2000]


def test_overview(session: Session, category) -> None:
    settings_core.set_monthly_target(session, 100000)
    _add(session, category, TODAY, 25000)
    _add(session, category, date(2026, 9, 1), 25000, "Locuință")
    view = reports.overview(session, TODAY)
    assert view.day.total_minor == 25000
    assert view.month.total_minor == 50000
    assert view.target_share_pct == 50.0
    assert view.unrated == 1
    assert view.top_categories[0].name in ("Alimente", "Locuință")


def test_month_calendar(session: Session, category) -> None:
    _add(session, category, date(2026, 9, 1), 1000)
    _add(session, category, date(2026, 9, 1), 500)
    _add(session, category, date(2026, 9, 29), 2000)
    _add(session, category, date(2026, 10, 1), 9000)  # outside the month, but on the grid
    calendar = reports.month_calendar(session, TODAY)
    assert calendar.period.start == date(2026, 9, 1)
    assert calendar.weeks[0][0].day == date(2026, 8, 31)  # the grid starts on a Monday
    assert calendar.weeks[-1][-1].day == date(2026, 10, 4)
    assert all(len(week) == 7 for week in calendar.weeks)
    first = calendar.weeks[0][1]
    assert (first.day, first.in_month, first.total_minor, first.count) == (
        date(2026, 9, 1),
        True,
        1500,
        2,
    )
    october = calendar.weeks[-1][3]
    assert (october.day, october.in_month, october.total_minor) == (date(2026, 10, 1), False, 9000)
    assert calendar.total_minor == 3500
    assert calendar.max_day_minor == 2000
