"""The Reports page: one period, the 12-month trend, the category table, flagged and recurring."""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from spendtrack.core import reports as core
from spendtrack.core.errors import ValidationError
from spendtrack.core.expenses import NECESSITY_NAMES, UNRATED_NAME
from spendtrack.core.money import to_decimal
from spendtrack.core.periods import KINDS, month_short, next_period, previous_period
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render, today_for

router = APIRouter(prefix="/reports")


@router.get("")
def reports_page(
    request: Request, db: Session = DbDep, kind: str = "week", date_text: str | None = None
) -> Response:
    today = today_for(request)
    if kind not in KINDS:
        kind = "week"
    raw = request.query_params.get("date")
    try:
        anchor: date = forms.parse_date(raw, default=today)
    except ValidationError:
        anchor = today
    report = core.period_report(db, kind, anchor, today)
    trend = core.necessity_trend(db, today, months=12)
    table = core.category_by_month(db, today, months=12)
    chart = {
        "labels": [month_short(point.period.start) for point in trend],
        "datasets": [
            {
                "label": name,
                "data": [float(to_decimal(point.by_necessity[level])) for point in trend],
            }
            for level, name in [*NECESSITY_NAMES.items(), (None, UNRATED_NAME)]
        ],
    }
    return render(
        request,
        db,
        "reports.html",
        {
            "kind": kind,
            "anchor": anchor,
            "report": report,
            "flagged": core.flagged_lines(report.lines),
            "recurring": core.recurring_lines(report.lines),
            "trend": trend,
            "table": table,
            "chart_json": json.dumps(chart),
            "prev_date": previous_period(report.period).start,
            "next_date": next_period(report.period).start,
            "is_future": next_period(report.period).start > today,
        },
    )
