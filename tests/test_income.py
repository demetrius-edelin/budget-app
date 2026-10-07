from datetime import date

import pytest
from sqlalchemy.orm import Session

from spendtrack.core import expenses as expenses_core
from spendtrack.core import income as core
from spendtrack.core import reports
from spendtrack.core import settings as settings_core
from spendtrack.core.errors import NotFoundError, ValidationError
from spendtrack.core.periods import period_for
from tests.conftest import TODAY


def _add(session: Session, minor: int, day: date = TODAY, description: str | None = "Bonus"):
    return core.add_income(
        session, received_on=day, amount_minor=minor, description=description, today=TODAY
    )


def test_add_income_in_the_current_month(session: Session) -> None:
    first = _add(session, 50000, date(2026, 9, 30))
    second = _add(session, 2500, date(2026, 9, 1), description="  ")
    rows = core.list_income(session, period_for("month", TODAY))
    assert [row.id for row in rows] == [second.id, first.id]
    assert second.description is None
    assert core.list_income(session, period_for("month", date(2026, 10, 1))) == []


@pytest.mark.parametrize(
    ("minor", "day", "message"),
    [
        (0, TODAY, "mai mare decât zero"),
        (-100, TODAY, "mai mare decât zero"),
        (100, date(2026, 8, 31), "luna curentă"),
        (100, date(2026, 10, 1), "luna curentă"),
    ],
)
def test_add_income_rejects_bad_input(
    session: Session, minor: int, day: date, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _add(session, minor, day)
    assert core.list_income(session, period_for("month", day)) == []


def test_income_raises_the_target_of_its_month_only(session: Session, category) -> None:
    settings_core.set_monthly_target(session, 100000)
    expenses_core.create_expense(
        session, occurred_on=TODAY, amount_minor=50000, category_id=category("Alimente")
    )
    _add(session, 25000, date(2026, 9, 30))
    view = reports.overview(session, TODAY)
    assert (view.monthly_target_minor, view.extra_income_minor) == (100000, 25000)
    assert view.month_limit_minor == 125000
    assert view.target_share_pct == 40.0
    october = reports.overview(session, date(2026, 10, 5))
    assert (october.extra_income_minor, october.month_limit_minor) == (0, 100000)


def test_deleted_income_does_not_count_until_restored(session: Session) -> None:
    settings_core.set_monthly_target(session, 100000)
    income = _add(session, 25000)
    core.delete_income(session, income.id)
    assert reports.overview(session, TODAY).month_limit_minor == 100000
    with pytest.raises(NotFoundError):
        core.delete_income(session, income.id)
    core.restore_income(session, income.id)
    assert reports.overview(session, TODAY).month_limit_minor == 125000


def test_income_without_a_target_sets_no_limit(session: Session) -> None:
    _add(session, 25000)
    view = reports.overview(session, TODAY)
    assert view.extra_income_minor == 25000
    assert (view.month_limit_minor, view.target_share_pct) == (None, None)
