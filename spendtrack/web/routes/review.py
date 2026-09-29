"""The Review page: unrated expenses one at a time, with keyboard shortcuts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from spendtrack.core import expenses as core
from spendtrack.core.errors import SpendtrackError
from spendtrack.core.money import parse_optional_amount
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render

router = APIRouter(prefix="/review")


def _card_context(db: Session, index: int, error: str | None = None) -> dict[str, Any]:
    queue = core.review_queue(db)
    if queue:
        index = max(0, min(index, len(queue) - 1))
    else:
        index = 0
    return {
        "queue_size": len(queue),
        "index": index,
        "entry": queue[index] if queue else None,
        "error": error,
    }


@router.get("")
def review_page(request: Request, db: Session = DbDep, index: int = 0) -> Response:
    return render(request, db, "review.html", _card_context(db, index))


@router.get("/card")
def review_card(request: Request, db: Session = DbDep, index: int = 0) -> Response:
    return render(request, db, "partials/review_card.html", _card_context(db, index))


@router.post("/{expense_id}/rate")
async def review_rate(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    index = forms.parse_optional_int(params.get("index"), "index") or 0
    try:
        level = forms.parse_necessity(params.get("level"))
        if level is None:
            raise SpendtrackError("Pick a level from 1 to 4.")
        core.update_expense(db, expense_id, necessity=level)
    except SpendtrackError as exc:
        return render(request, db, "partials/review_card.html", _card_context(db, index, str(exc)))
    db.commit()
    return render(request, db, "partials/review_card.html", _card_context(db, index))


@router.post("/{expense_id}/toggle")
async def review_toggle(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    index = forms.parse_optional_int(params.get("index"), "index") or 0
    flag = forms.text(params, "flag")
    try:
        expense = core.get_expense(db, expense_id)
        if flag == "cheaper":
            core.update_expense(db, expense_id, cheaper_alt=not expense.cheaper_alt)
        elif flag == "recurring":
            core.update_expense(db, expense_id, recurring=not expense.recurring)
        else:
            raise SpendtrackError("Unknown flag.")
    except SpendtrackError as exc:
        return render(request, db, "partials/review_card.html", _card_context(db, index, str(exc)))
    db.commit()
    return render(request, db, "partials/review_card.html", _card_context(db, index))


@router.post("/{expense_id}/price")
async def review_price(request: Request, expense_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    index = forms.parse_optional_int(params.get("index"), "index") or 0
    try:
        minor = parse_optional_amount(forms.text(params, "cheaper_alt_amount"))
        core.update_expense(db, expense_id, cheaper_alt=True, cheaper_alt_minor=minor)
    except SpendtrackError as exc:
        return render(request, db, "partials/review_card.html", _card_context(db, index, str(exc)))
    db.commit()
    return render(request, db, "partials/review_card.html", _card_context(db, index))
