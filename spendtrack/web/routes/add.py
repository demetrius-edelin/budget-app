"""The Add page: the expense form and the metric form."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from spendtrack.core import categories as categories_core
from spendtrack.core import expenses as expenses_core
from spendtrack.core import metrics as metrics_core
from spendtrack.core import settings as settings_core
from spendtrack.core.errors import SpendtrackError
from spendtrack.core.money import (
    parse_amount,
    parse_decimal,
    parse_optional_amount,
    parse_optional_decimal,
)
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render, today_for

router = APIRouter(prefix="/add")


def _page_context(db: Session, today: date, **extra: Any) -> dict[str, Any]:
    metric_types = metrics_core.list_metric_types(db)
    context: dict[str, Any] = {
        "categories": categories_core.list_categories(db),
        "metric_types": metric_types,
        "fuel_category_id": metric_types[0].category_id if metric_types else None,
        "fuel_cost_mode": settings_core.fuel_cost_mode(db),
        "expense_values": {"occurred_on": today.isoformat()},
        "metric_values": {"occurred_on": today.isoformat()},
        "expense_error": None,
        "metric_error": None,
        "saved": None,
        "saved_calculation": None,
    }
    context.update(extra)
    return context


@router.get("")
def add_page(request: Request, db: Session = DbDep, saved: int | None = None) -> Response:
    today = today_for(request)
    context = _page_context(db, today)
    if saved is not None:
        try:
            expense = expenses_core.get_expense(db, saved)
        except SpendtrackError:
            expense = None
        if expense is not None:
            context["saved"] = expense
            entry = metrics_core.entry_for_expense(db, expense)
            if entry is not None:
                context["saved_calculation"] = metrics_core.calculation_text(entry)
    return render(request, db, "add.html", context)


def _common_flags(params: dict[str, str]) -> dict[str, Any]:
    """Read the necessity, cheaper and recurring fields shared by both forms."""
    return {
        "necessity": forms.parse_necessity(forms.text(params, "necessity")),
        "cheaper_alt": forms.parse_bool(params.get("cheaper_alt")),
        "cheaper_alt_minor": parse_optional_amount(forms.text(params, "cheaper_alt_amount")),
        "cheaper_alt_note": forms.text(params, "cheaper_alt_note"),
        "recurring": forms.parse_bool(params.get("recurring")),
    }


@router.post("/expense")
async def add_expense(request: Request, db: Session = DbDep) -> Response:
    today = today_for(request)
    params = await forms.all_params(request)
    try:
        expense = expenses_core.create_expense(
            db,
            occurred_on=forms.parse_date(params.get("occurred_on"), default=today),
            amount_minor=parse_amount(params.get("amount")),
            category_id=forms.parse_int(params.get("category_id"), "categoria"),
            description=forms.text(params, "description"),
            **_common_flags(params),
        )
    except SpendtrackError as exc:
        context = _page_context(db, today, expense_values=params, expense_error=str(exc))
        return render(request, db, "add.html", context, status_code=400)
    db.commit()
    return RedirectResponse(url=f"/add?saved={expense.id}", status_code=303)


def _metric_input(params: dict[str, str], today: date) -> dict[str, Any]:
    overrides: dict[str, Decimal] = {}
    consumption = parse_optional_decimal(params.get("consumption"), "consumul")
    price = parse_optional_decimal(params.get("fuel_price"), "prețul combustibilului")
    if consumption is not None:
        overrides["consumption_l_per_100km"] = consumption
    if price is not None:
        overrides["fuel_price_per_l"] = price
    return {
        "metric_key": forms.text(params, "metric_key") or "drive",
        "occurred_on": forms.parse_date(params.get("occurred_on"), default=today),
        "quantity": parse_decimal(params.get("quantity"), "distanța în km"),
        "overrides": overrides,
    }


@router.post("/metric")
async def add_metric(request: Request, db: Session = DbDep) -> Response:
    today = today_for(request)
    params = await forms.all_params(request)
    try:
        entry = metrics_core.create_metric_entry(
            db,
            **_metric_input(params, today),
            description=forms.text(params, "description"),
            **_common_flags(params),
        )
    except SpendtrackError as exc:
        context = _page_context(db, today, metric_values=params, metric_error=str(exc))
        return render(request, db, "add.html", context, status_code=400)
    db.commit()
    return RedirectResponse(url=f"/add?saved={entry.expense_id}", status_code=303)


@router.post("/metric/preview")
async def metric_preview(request: Request, db: Session = DbDep) -> Response:
    """Return the live preview partial for the metric form."""
    today = today_for(request)
    params = await forms.all_params(request)
    try:
        result = metrics_core.quote(db, **_metric_input(params, today))
    except SpendtrackError as exc:
        return render(request, db, "partials/metric_preview.html", {"error": str(exc)})
    return render(request, db, "partials/metric_preview.html", {"quote": result})
