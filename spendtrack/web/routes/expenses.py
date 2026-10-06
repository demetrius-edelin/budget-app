"""The Expenses page: the period bar, filters, inline edits, items, Undo for deletes, CSV export."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from spendtrack.core import categories as categories_core
from spendtrack.core import expenses as core
from spendtrack.core import metrics as metrics_core
from spendtrack.core.errors import SpendtrackError
from spendtrack.core.expenses import ItemInput, Line, necessity_name
from spendtrack.core.money import parse_amount, parse_optional_amount, to_decimal
from spendtrack.core.periods import (
    KINDS,
    Period,
    match_period,
    next_period,
    period_for,
    period_label,
    previous_period,
)
from spendtrack.db.models import Expense
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render, today_for

router = APIRouter()

LIST_LIMIT = 500


@dataclass(frozen=True)
class Filters:
    start: date | None = None
    end: date | None = None
    category_id: int | None = None
    necessity: int | str | None = None
    cheaper: bool | None = None
    recurring: bool | None = None
    q: str | None = None

    @classmethod
    def from_params(cls, params: dict[str, str]) -> Filters:
        """Read the filters. A 'date' with a 'kind' sets the start and the end to that period."""
        necessity_text = forms.text(params, "necessity")
        necessity: int | str | None = None
        if necessity_text == "unrated":
            necessity = "unrated"
        elif necessity_text:
            necessity = forms.parse_necessity(necessity_text)
        start = forms.parse_optional_date(params.get("start"), "data de început")
        end = forms.parse_optional_date(params.get("end"), "data de sfârșit")
        day = forms.parse_optional_date(params.get("date"))
        if day is not None:
            kind = params.get("kind")
            period = period_for(kind if kind in KINDS else "day", day)
            start, end = period.start, period.end
        return cls(
            start=start,
            end=end,
            category_id=forms.parse_optional_int(params.get("category_id"), "categoria"),
            necessity=necessity,
            cheaper=forms.parse_optional_bool(params.get("cheaper")),
            recurring=forms.parse_optional_bool(params.get("recurring")),
            q=forms.text(params, "q"),
        )

    def as_dict(self) -> dict[str, str]:
        values = {
            "start": self.start.isoformat() if self.start else "",
            "end": self.end.isoformat() if self.end else "",
            "category_id": str(self.category_id) if self.category_id else "",
            "necessity": str(self.necessity) if self.necessity is not None else "",
            "cheaper": "" if self.cheaper is None else ("1" if self.cheaper else "0"),
            "recurring": "" if self.recurring is None else ("1" if self.recurring else "0"),
            "q": self.q or "",
        }
        return values

    def query_string(self) -> str:
        return urlencode({k: v for k, v in self.as_dict().items() if v})

    def url(self, start: date | None, end: date | None) -> str:
        """Return the URL of the Expenses page with these filters and another date range."""
        query = replace(self, start=start, end=end).query_string()
        return f"/expenses?{query}" if query else "/expenses"

    def matching_lines(self, expense: Expense) -> list[Line] | None:
        """Return the lines at the necessity of the filter. Return None without that filter."""
        if self.necessity is None:
            return None
        level = self.necessity if isinstance(self.necessity, int) else None
        return core.lines_with_necessity(expense, level)

    def apply(self, db: Session, *, limit: int | None = LIST_LIMIT) -> list[Any]:
        return core.list_expenses(
            db,
            start=self.start,
            end=self.end,
            category_id=self.category_id,
            necessity=self.necessity,
            cheaper=self.cheaper,
            recurring=self.recurring,
            search=self.q,
            limit=limit,
        )


def _amount(minor: int | None) -> str:
    """Format minor units for a CSV cell, with a dot as the decimal separator."""
    return "" if minor is None else f"{to_decimal(minor):.2f}"


def _view_totals(db: Session, filters: Filters) -> dict[str, Any]:
    """Return the total of the view. With a necessity filter, count only the lines at that level."""
    expenses = filters.apply(db, limit=None)
    total = 0
    for expense in expenses:
        if expense.informational:
            continue
        lines = filters.matching_lines(expense)
        total += expense.amount_minor if lines is None else sum(line.amount_minor for line in lines)
    level = None
    if filters.necessity is not None:
        level = necessity_name(filters.necessity if isinstance(filters.necessity, int) else None)
    return {"total": total, "count": len(expenses), "level": level}


def _partial_match(filters: Filters, expense: Expense) -> list[Line] | None:
    """Return the matching lines when only a part of the expense matches the necessity filter."""
    lines = filters.matching_lines(expense)
    if lines is None or sum(line.amount_minor for line in lines) >= expense.amount_minor:
        return None
    return lines


def _anchor(filters: Filters, today: date) -> date:
    """Return the day for the Zi, Săptămână and Lună buttons: today, if the date range holds it."""
    start, end = filters.start, filters.end
    if (start is None or start <= today) and (end is None or today <= end):
        return today
    return start or end or today


def _period_nav(filters: Filters, today: date) -> dict[str, Any]:
    """Return the period bar: Toate, Zi, Săptămână, Lună, Anterior, the date, Următor and Azi.

    The active period comes from the start and the end of the filters.
    """
    period: Period | None = None
    if filters.start is not None and filters.end is not None:
        period = match_period(filters.start, filters.end)
    anchor = _anchor(filters, today)

    def url(span: Period) -> str:
        return filters.url(span.start, span.end)

    active = period.kind if period else None
    if filters.start is None and filters.end is None:
        active = "all"
    buttons = [("all", "Toate", filters.url(None, None))]
    for kind, label in (("day", "Zi"), ("week", "Săptămână"), ("month", "Lună")):
        buttons.append((kind, label, url(period_for(kind, anchor))))
    following = next_period(period) if period else None
    return {
        "active": active,
        "buttons": buttons,
        "label": period_label(period) if period else None,
        "anchor": anchor if period else None,
        "kind": period.kind if period else "day",
        "previous": url(previous_period(period)) if period else None,
        "next": url(following) if following and following.start <= today else None,
        "today": url(period_for(period.kind if period else "day", today)),
        "hidden": {k: v for k, v in filters.as_dict().items() if v and k not in ("start", "end")},
    }


def _block_context(
    db: Session,
    expense_id: int,
    params: dict[str, str],
    *,
    expanded: bool = False,
    mode: str = "view",
    editing_item_id: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    expense = core.get_expense(db, expense_id, include_deleted=True)
    try:
        filters = Filters.from_params(params)
    except SpendtrackError:
        filters = Filters()
    entry = metrics_core.entry_for_expense(db, expense)
    return {
        "expense": expense,
        "match_lines": _partial_match(filters, expense),
        "expanded": expanded or editing_item_id is not None,
        "mode": mode,
        "editing_item_id": editing_item_id,
        "error": error,
        "calculation": metrics_core.calculation_text(entry) if entry else None,
        "categories": categories_core.list_categories(db, include_archived=True),
        "totals": _view_totals(db, filters),
        "oob": True,
    }


def _block(request: Request, db: Session, context: dict[str, Any], status_code: int = 200):
    return render(request, db, "partials/expense_block.html", context, status_code=status_code)


@router.get("/expenses")
def expenses_page(request: Request, db: Session = DbDep) -> Response:
    params = dict(request.query_params)
    error = None
    try:
        filters = Filters.from_params(params)
    except SpendtrackError as exc:
        filters = Filters()
        error = str(exc)
    expenses = filters.apply(db)
    matches = {expense.id: _partial_match(filters, expense) for expense in expenses}
    return render(
        request,
        db,
        "expenses.html",
        {
            "expenses": expenses,
            "matches": matches,
            "nav": _period_nav(filters, today_for(request)),
            "filters": filters.as_dict(),
            "query_string": filters.query_string(),
            "totals": _view_totals(db, filters),
            "categories": categories_core.list_categories(db, include_archived=True),
            "error": error,
            "limit": LIST_LIMIT,
            "oob": False,
        },
    )


@router.get("/expenses/export.csv")
def export_csv(request: Request, db: Session = DbDep, mode: str = "expenses") -> Response:
    """Export the filtered view: one row per expense, or one row per breakdown line.

    With a necessity filter, the line export has only the lines at that level.
    """
    filters = Filters.from_params(dict(request.query_params))
    expenses = filters.apply(db, limit=None)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if mode == "lines":
        writer.writerow(
            [
                "expense_id",
                "item_id",
                "date",
                "category",
                "description",
                "amount",
                "necessity",
                "cheaper_alt",
                "cheaper_alt_amount",
                "potential_saving",
                "recurring",
                "is_remainder",
                "source",
                "informational",
            ]
        )
        for expense in expenses:
            lines = filters.matching_lines(expense)
            for line in core.expense_lines(expense) if lines is None else lines:
                writer.writerow(
                    [
                        line.expense_id,
                        line.item_id or "",
                        line.occurred_on.isoformat(),
                        line.category_name,
                        line.description,
                        _amount(line.amount_minor),
                        necessity_name(line.necessity),
                        int(line.cheaper_alt),
                        _amount(line.cheaper_alt_minor),
                        _amount(line.potential_saving_minor),
                        int(line.recurring),
                        int(line.is_remainder),
                        line.source,
                        int(expense.informational),
                    ]
                )
        filename = "spendtrack-lines.csv"
    else:
        writer.writerow(
            [
                "id",
                "date",
                "category",
                "description",
                "amount",
                "currency",
                "necessity",
                "cheaper_alt",
                "cheaper_alt_amount",
                "cheaper_alt_note",
                "recurring",
                "source",
                "informational",
                "items",
            ]
        )
        for expense in expenses:
            writer.writerow(
                [
                    expense.id,
                    expense.occurred_on.isoformat(),
                    expense.category.name,
                    expense.description or "",
                    _amount(expense.amount_minor),
                    expense.currency,
                    necessity_name(expense.necessity),
                    int(expense.cheaper_alt),
                    _amount(expense.cheaper_alt_minor),
                    expense.cheaper_alt_note or "",
                    int(expense.recurring),
                    expense.source,
                    int(expense.informational),
                    len(expense.live_items),
                ]
            )
        filename = "spendtrack-expenses.csv"
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers=headers)


@router.get("/expenses/{expense_id}/row")
async def expense_row(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    expanded = forms.parse_bool(params.get("expanded"))
    return _block(request, db, _block_context(db, expense_id, params, expanded=expanded))


@router.get("/expenses/{expense_id}/edit")
async def expense_edit_form(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    return _block(request, db, _block_context(db, expense_id, params, mode="edit"))


@router.post("/expenses/{expense_id}/edit")
async def expense_edit(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    expanded = forms.parse_bool(params.get("expanded"))
    try:
        changes: dict[str, Any] = {
            "occurred_on": forms.parse_date(params.get("occurred_on")),
            "category_id": forms.parse_int(params.get("category_id"), "categoria"),
            "description": forms.text(params, "description"),
            "necessity": forms.parse_necessity(forms.text(params, "necessity")),
            "cheaper_alt": forms.parse_bool(params.get("cheaper_alt")),
            "cheaper_alt_minor": parse_optional_amount(forms.text(params, "cheaper_alt_amount")),
            "cheaper_alt_note": forms.text(params, "cheaper_alt_note"),
            "recurring": forms.parse_bool(params.get("recurring")),
        }
        expense = core.get_expense(db, expense_id)
        if expense.source != "metric":
            changes["amount_minor"] = parse_amount(params.get("amount"))
        core.update_expense(db, expense_id, **changes)
    except SpendtrackError as exc:
        context = _block_context(db, expense_id, params, mode="edit", error=str(exc))
        return _block(request, db, context, status_code=400)
    db.commit()
    return _block(request, db, _block_context(db, expense_id, params, expanded=expanded))


@router.post("/expenses/{expense_id}/delete")
async def expense_delete(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    core.delete_expense(db, expense_id)
    db.commit()
    return _block(request, db, _block_context(db, expense_id, params, mode="deleted"))


@router.get("/expenses/{expense_id}/gone")
async def expense_gone(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    """Remove a deleted row from the page. A restored expense shows its row again."""
    expense = core.get_expense(db, expense_id, include_deleted=True)
    if expense.deleted_at is not None:
        return Response("", media_type="text/html")
    params = await forms.all_params(request)
    return _block(request, db, _block_context(db, expense_id, params))


@router.post("/expenses/{expense_id}/restore")
async def expense_restore(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    core.restore_expense(db, expense_id)
    db.commit()
    return _block(request, db, _block_context(db, expense_id, params))


def _item_fields(params: dict[str, str]) -> dict[str, Any]:
    category_id = forms.parse_optional_int(params.get("item_category_id"), "categoria")
    return {
        "description": forms.text(params, "item_description") or "",
        "amount_minor": parse_amount(params.get("item_amount")),
        "category_id": category_id,
        "necessity": forms.parse_necessity(forms.text(params, "item_necessity")),
        "cheaper_alt": forms.parse_bool(params.get("item_cheaper_alt")),
        "cheaper_alt_minor": parse_optional_amount(forms.text(params, "item_cheaper_alt_amount")),
        "cheaper_alt_note": forms.text(params, "item_cheaper_alt_note"),
    }


@router.post("/expenses/{expense_id}/items")
async def item_add(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    try:
        core.add_items(db, expense_id, [ItemInput(**_item_fields(params))])
    except SpendtrackError as exc:
        context = _block_context(db, expense_id, params, expanded=True, error=str(exc))
        return _block(request, db, context, status_code=400)
    db.commit()
    return _block(request, db, _block_context(db, expense_id, params, expanded=True))


@router.get("/items/{item_id}/edit")
async def item_edit_form(request: Request, item_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    item = core.get_item(db, item_id)
    context = _block_context(db, item.expense_id, params, editing_item_id=item.id)
    return _block(request, db, context)


@router.post("/items/{item_id}/edit")
async def item_edit(request: Request, item_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    item = core.get_item(db, item_id)
    try:
        core.update_item(db, item_id, **_item_fields(params))
    except SpendtrackError as exc:
        context = _block_context(
            db, item.expense_id, params, editing_item_id=item.id, error=str(exc)
        )
        return _block(request, db, context, status_code=400)
    db.commit()
    return _block(request, db, _block_context(db, item.expense_id, params, expanded=True))


@router.post("/items/{item_id}/delete")
async def item_delete(request: Request, item_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    item = core.delete_item(db, item_id)
    db.commit()
    return _block(request, db, _block_context(db, item.expense_id, params, expanded=True))


@router.post("/items/{item_id}/restore")
async def item_restore(request: Request, item_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    item = core.get_item(db, item_id, include_deleted=True)
    try:
        core.restore_item(db, item_id)
    except SpendtrackError as exc:
        context = _block_context(db, item.expense_id, params, expanded=True, error=str(exc))
        return _block(request, db, context, status_code=400)
    db.commit()
    return _block(request, db, _block_context(db, item.expense_id, params, expanded=True))
