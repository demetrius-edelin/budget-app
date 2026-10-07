"""The Overview page, and the forms for the extra income of the month."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from spendtrack.core import fx, reports
from spendtrack.core import income as income_core
from spendtrack.core.errors import NotFoundError, SpendtrackError
from spendtrack.core.money import parse_amount
from spendtrack.core.periods import next_period, previous_period
from spendtrack.db.models import Income
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render, today_for

router = APIRouter()


def _month_anchor(text: str | None, today: date) -> date:
    """Parse a YYYY-MM value into the first day of that month, or return today."""
    if not text:
        return today
    try:
        return date.fromisoformat(f"{text.strip()[:7]}-01")
    except ValueError:
        return today


def _deleted_income(db: Session, value: str | None) -> Income | None:
    """Return the deleted extra income that the Undo banner offers to restore."""
    if not value or not value.isdigit():
        return None
    try:
        income = income_core.get_income(db, int(value), include_deleted=True)
    except NotFoundError:
        return None
    return income if income.deleted_at is not None else None


def _render_overview(
    request: Request,
    db: Session,
    month: str | None = None,
    *,
    status_code: int = 200,
    **extra: Any,
) -> Response:
    today = today_for(request)
    view = reports.overview(db, today)
    calendar = reports.month_calendar(db, _month_anchor(month, today))
    config = request.app.state.config
    rate = fx.eur_rate(config.fx_dir, today, fetch=request.app.state.fx_fetch)
    context: dict[str, Any] = {
        "view": view,
        "fx": rate,
        "calendar": calendar,
        "prev_month": previous_period(calendar.period).start.strftime("%Y-%m"),
        "next_month": next_period(calendar.period).start.strftime("%Y-%m"),
        "show_next": next_period(calendar.period).start <= today,
        "income_form": {},
        "income_error": None,
        "deleted_income": None,
    }
    context.update(extra)
    return render(request, db, "overview.html", context, status_code=status_code)


@router.get("/")
def overview_page(
    request: Request,
    db: Session = DbDep,
    month: str | None = None,
    income_deleted: str | None = None,
) -> Response:
    return _render_overview(request, db, month, deleted_income=_deleted_income(db, income_deleted))


@router.post("/income")
async def income_add(request: Request, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    today = today_for(request)
    try:
        income_core.add_income(
            db,
            received_on=forms.parse_date(
                params.get("received_on"), default=today, label="data venitului"
            ),
            amount_minor=parse_amount(forms.text(params, "amount")),
            description=forms.text(params, "description"),
            today=today,
        )
    except SpendtrackError as exc:
        db.rollback()
        return _render_overview(
            request, db, status_code=400, income_error=str(exc), income_form=params
        )
    db.commit()
    return RedirectResponse(url="/#month-target", status_code=303)


@router.post("/income/{income_id}/delete")
async def income_delete(request: Request, income_id: int, db: Session = DbDep) -> Response:
    income_core.delete_income(db, income_id)
    db.commit()
    return RedirectResponse(url=f"/?income_deleted={income_id}#month-target", status_code=303)


@router.post("/income/{income_id}/restore")
async def income_restore(request: Request, income_id: int, db: Session = DbDep) -> Response:
    income_core.restore_income(db, income_id)
    db.commit()
    return RedirectResponse(url="/#month-target", status_code=303)
