"""Extra income. An extra income raises the monthly target for the month of the income only."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendtrack.core.errors import NotFoundError, ValidationError
from spendtrack.core.periods import Period, period_for
from spendtrack.db.models import Income, utcnow


def get_income(session: Session, income_id: int, *, include_deleted: bool = False) -> Income:
    """Return the extra income, or raise NotFoundError."""
    income = session.get(Income, income_id)
    if income is None or (income.deleted_at is not None and not include_deleted):
        raise NotFoundError(f"Venitul #{income_id} nu există.")
    return income


def add_income(
    session: Session,
    *,
    received_on: date,
    amount_minor: int,
    description: str | None,
    today: date,
) -> Income:
    """Add an extra income. The date must be in the month of today.

    The Overview shows only the current month, so an income in another month
    is not visible there.
    """
    if amount_minor <= 0:
        raise ValidationError("Suma trebuie să fie mai mare decât zero.")
    if not period_for("month", today).contains(received_on):
        raise ValidationError("Data venitului trebuie să fie în luna curentă.")
    income = Income(
        received_on=received_on,
        amount_minor=amount_minor,
        description=(description or "").strip() or None,
    )
    session.add(income)
    session.flush()
    return income


def list_income(session: Session, period: Period) -> list[Income]:
    """Return the extra income of the period that is not deleted, oldest first."""
    rows = session.scalars(
        select(Income)
        .where(
            Income.deleted_at.is_(None),
            Income.received_on >= period.start,
            Income.received_on <= period.end,
        )
        .order_by(Income.received_on, Income.id)
    )
    return list(rows)


def delete_income(session: Session, income_id: int) -> Income:
    income = get_income(session, income_id)
    income.deleted_at = utcnow()
    session.flush()
    return income


def restore_income(session: Session, income_id: int) -> Income:
    income = get_income(session, income_id, include_deleted=True)
    income.deleted_at = None
    session.flush()
    return income
