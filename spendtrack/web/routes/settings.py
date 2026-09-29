"""The Settings page: categories, metric parameters, fuel cost mode, target, format, backups."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from spendtrack.core import backup as backup_core
from spendtrack.core import categories as categories_core
from spendtrack.core import metrics as metrics_core
from spendtrack.core import settings as settings_core
from spendtrack.core.errors import SpendtrackError
from spendtrack.core.money import parse_decimal, parse_optional_amount
from spendtrack.web import forms
from spendtrack.web.app import DbDep, render, today_for

router = APIRouter(prefix="/settings")


def _context(request: Request, db: Session, **extra: Any) -> dict[str, Any]:
    config = request.app.state.config
    metric_types = metrics_core.list_metric_types(db)
    history = {mt.key: metrics_core.param_history(db, mt.key) for mt in metric_types}
    context: dict[str, Any] = {
        "categories": categories_core.list_categories(db, include_archived=True),
        "metric_types": metric_types,
        "param_names": {mt.key: metrics_core.param_names(mt) for mt in metric_types},
        "param_label": metrics_core.param_label,
        "history": history,
        "fuel_cost_mode": settings_core.fuel_cost_mode(db),
        "monthly_target_minor": settings_core.monthly_target_minor(db),
        "number_format": settings_core.number_format(db),
        "backup_keep_days": settings_core.backup_keep_days(db),
        "backups": backup_core.list_backups(config.backup_dir)[:5],
        "data_dir": str(config.data_dir),
        "telegram_on": bool(config.telegram_bot_token),
        "telegram_ids": len(config.allowed_telegram_user_ids),
        "ai_provider": config.ai_provider,
        "ai_model": config.ai_model,
        "error": None,
        "ok": request.query_params.get("ok") == "1",
    }
    context.update(extra)
    return context


@router.get("")
def settings_page(request: Request, db: Session = DbDep) -> Response:
    return render(request, db, "settings.html", _context(request, db))


def _fail(request: Request, db: Session, message: str) -> Response:
    db.rollback()
    context = _context(request, db, error=message)
    return render(request, db, "settings.html", context, status_code=400)


@router.post("/general")
async def settings_general(request: Request, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    try:
        settings_core.set_fuel_cost_mode(db, forms.text(params, "fuel_cost_mode") or "km")
        settings_core.set_number_format(db, forms.text(params, "number_format") or "ro-RO")
        settings_core.set_monthly_target(
            db, parse_optional_amount(forms.text(params, "monthly_target"))
        )
        settings_core.set_backup_keep_days(
            db, forms.parse_int(params.get("backup_keep_days"), "numărul de copii de rezervă")
        )
    except SpendtrackError as exc:
        return _fail(request, db, str(exc))
    db.commit()
    return RedirectResponse(url="/settings?ok=1", status_code=303)


@router.post("/categories")
async def category_add(request: Request, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    try:
        categories_core.create_category(
            db,
            forms.text(params, "name") or "",
            default_necessity=forms.parse_necessity(forms.text(params, "default_necessity")),
            default_recurring=forms.parse_bool(params.get("default_recurring")),
        )
    except SpendtrackError as exc:
        return _fail(request, db, str(exc))
    db.commit()
    return RedirectResponse(url="/settings?ok=1#categories", status_code=303)


@router.post("/categories/{category_id}")
async def category_update(request: Request, category_id: int, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    try:
        categories_core.update_category(
            db,
            category_id,
            name=forms.text(params, "name") or "",
            default_necessity=forms.parse_necessity(forms.text(params, "default_necessity")),
            default_recurring=forms.parse_bool(params.get("default_recurring")),
            sort_order=forms.parse_int(params.get("sort_order"), "ordinea"),
            archived=forms.parse_bool(params.get("archived")),
        )
    except SpendtrackError as exc:
        return _fail(request, db, str(exc))
    db.commit()
    return RedirectResponse(url="/settings?ok=1#categories", status_code=303)


@router.post("/metrics/{metric_key}/params")
async def param_add(request: Request, metric_key: str, db: Session = DbDep) -> Response:
    params = await forms.all_params(request)
    today = today_for(request)
    try:
        name = forms.text(params, "name") or ""
        label = metrics_core.param_in_sentence(name)
        metrics_core.set_param(
            db,
            metric_key,
            name,
            parse_decimal(params.get("value"), label),
            forms.parse_date(
                params.get("effective_from"), default=today, label="data de valabilitate"
            ),
        )
    except SpendtrackError as exc:
        return _fail(request, db, str(exc))
    db.commit()
    return RedirectResponse(url="/settings?ok=1#metrics", status_code=303)


@router.post("/metrics/params/{param_id}/delete")
async def param_delete(request: Request, param_id: int, db: Session = DbDep) -> Response:
    try:
        metrics_core.delete_param(db, param_id)
    except SpendtrackError as exc:
        return _fail(request, db, str(exc))
    db.commit()
    return RedirectResponse(url="/settings?ok=1#metrics", status_code=303)
