"""The Overview page."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from spendtrack.core import fx, reports
from spendtrack.core.periods import next_period, previous_period
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


@router.get("/")
def overview_page(request: Request, db: Session = DbDep, month: str | None = None) -> Response:
    today = today_for(request)
    view = reports.overview(db, today)
    calendar = reports.month_calendar(db, _month_anchor(month, today))
    config = request.app.state.config
    rate = fx.eur_rate(config.fx_dir, today, fetch=request.app.state.fx_fetch)
    return render(
        request,
        db,
        "overview.html",
        {
            "view": view,
            "fx": rate,
            "calendar": calendar,
            "prev_month": previous_period(calendar.period).start.strftime("%Y-%m"),
            "next_month": next_period(calendar.period).start.strftime("%Y-%m"),
            "show_next": next_period(calendar.period).start <= today,
        },
    )
