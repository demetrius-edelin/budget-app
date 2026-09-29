"""Build the FastAPI app. The app holds the config and the session factory in its state."""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from spendtrack.config import Config
from spendtrack.core import backup as backup_core
from spendtrack.core import fx
from spendtrack.core import settings as settings_core
from spendtrack.core.errors import NotFoundError, SpendtrackError
from spendtrack.core.expenses import (
    NECESSITY_NAMES,
    expense_lines,
    items_total,
    necessity_name,
    remainder_minor,
    unrated_count,
)
from spendtrack.core.money import format_decimal, format_minor
from spendtrack.core.periods import month_short, period_label, short_date

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def _money(minor: int | None, number_format: str = "ro-RO") -> str:
    if minor is None:
        return "–"
    return format_minor(minor, number_format)


def _pct(value: float | None) -> str:
    if value is None:
        return "–"
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):.1f}%"


def _short_date(value: date | None) -> str:
    if value is None:
        return ""
    return short_date(value)


def _month_short(value: date | None) -> str:
    if value is None:
        return ""
    return month_short(value)


def _rate(value: Decimal | None) -> str:
    """Format an exchange rate with four decimals and a comma."""
    if value is None:
        return ""
    return f"{value:.4f}".replace(".", ",")


def _iso(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def _decimal(value: Decimal | str | None) -> str:
    if value is None:
        return ""
    return format_decimal(Decimal(value))


templates.env.filters.update(
    {
        "money": _money,
        "pct": _pct,
        "short_date": _short_date,
        "iso": _iso,
        "decimal": _decimal,
        "period_label": period_label,
        "month_short": _month_short,
        "rate": _rate,
        "eur": fx.convert_minor,
    }
)
templates.env.globals.update(
    {
        "NECESSITY_NAMES": NECESSITY_NAMES,
        "necessity_name": necessity_name,
        "expense_lines": expense_lines,
        "remainder_minor": remainder_minor,
        "items_total": items_total,
    }
)


def get_db(request: Request) -> Iterator[Session]:
    """Open a session for one request. Commit on success, roll back on error."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbDep = Depends(get_db)


def today_for(request: Request) -> date:
    config: Config = request.app.state.config
    return datetime.now(config.tz).date()


def render(
    request: Request,
    db: Session,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> Response:
    """Render a template with the shared context: number format, currency, today, unrated count."""
    base: dict[str, Any] = {
        "nf": settings_core.number_format(db),
        "currency": settings_core.currency(db),
        "today": today_for(request),
        "unrated": unrated_count(db),
        "is_htmx": request.headers.get("HX-Request") == "true",
    }
    if context:
        base.update(context)
    return templates.TemplateResponse(request, name, base, status_code=status_code)


async def _basic_auth_middleware(request: Request, call_next: Any) -> Response:
    config: Config = request.app.state.config
    if not (config.allow_remote and config.basic_auth_user and config.basic_auth_password):
        return await call_next(request)
    header = request.headers.get("Authorization", "")
    ok = False
    if header.startswith("Basic "):
        try:
            raw = base64.b64decode(header[6:]).decode()
            user, _, password = raw.partition(":")
            ok = secrets.compare_digest(user, config.basic_auth_user) and secrets.compare_digest(
                password, config.basic_auth_password
            )
        except (ValueError, UnicodeDecodeError):
            ok = False
    if not ok:
        return PlainTextResponse(
            "Sign in.", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Spendtrack"'}
        )
    return await call_next(request)


async def _hourly_backup(app: FastAPI) -> None:
    """Write the daily backup while the app stays open across days."""
    config: Config = app.state.config
    while True:
        await asyncio.sleep(3600)
        try:
            with app.state.session_factory() as db:
                keep = settings_core.backup_keep_days(db)
            today = datetime.now(config.tz).date()
            written = backup_core.backup_if_needed(config.db_path, config.backup_dir, keep, today)
            if written is not None:
                log.info("Backup written: %s", written)
        except Exception:  # noqa: BLE001
            log.exception("The backup failed")


def create_app(
    config: Config, session_factory: sessionmaker[Session], *, background_backup: bool = True
) -> FastAPI:
    """Create the app with its routes, static files, error handlers and middleware."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_hourly_backup(app)) if background_backup else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()

    app = FastAPI(title="Spendtrack", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config = config
    app.state.session_factory = session_factory
    app.state.fx_fetch = fx.fetch_rates_xml
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.middleware("http")(_basic_auth_middleware)

    @app.get("/favicon.ico", include_in_schema=False)
    async def _favicon() -> FileResponse:
        return FileResponse(WEB_DIR / "static" / "favicon.ico")

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> Response:
        return PlainTextResponse(str(exc), status_code=404)

    @app.exception_handler(SpendtrackError)
    async def _core_error(request: Request, exc: SpendtrackError) -> Response:
        return PlainTextResponse(str(exc), status_code=400)

    from spendtrack.web.routes import add, expenses, overview, reports, review, settings

    for module in (overview, add, expenses, review, reports, settings):
        app.include_router(module.router)
    return app
