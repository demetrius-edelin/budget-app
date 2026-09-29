"""The Expenses page: filters, inline edits, items, soft delete with Undo, and CSV export."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
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
from spendtrack.core.expenses import ItemInput, necessity_name
from spendtrack.core.money import parse_amount, parse_optional_amount, to_decimal
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render

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
        necessity_text = forms.text(params, "necessity")
        necessity: int | str | None = None
        if necessity_text == "unrated":
            necessity = "unrated"
        elif necessity_text:
            necessity = forms.parse_necessity(necessity_text)
        return cls(
            start=forms.parse_optional_date(params.get("start"), "data de început"),
            end=forms.parse_optional_date(params.get("end"), "data de sfârșit"),
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


def _view_totals(db: Session, filters: Filters) -> dict[str, int]:
    expenses = filters.apply(db, limit=None)
    counted = [e for e in expenses if not e.informational]
    return {"total": sum(e.amount_minor for e in counted), "count": len(expenses)}


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
    return render(
        request,
        db,
        "expenses.html",
        {
            "expenses": expenses,
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
    """Export the filtered view: one row per expense, or one row per breakdown line."""
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
            for line in core.expense_lines(expense):
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
