"""Parse form fields into core values. Every parser raises ValidationError on bad input."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import Request

from spendtrack.core.errors import ValidationError


async def all_params(request: Request) -> dict[str, str]:
    """Merge the query string and the form body into one dict. Form values win."""
    params: dict[str, str] = {key: value for key, value in request.query_params.items()}
    if request.method in ("POST", "PUT", "PATCH"):
        form = await request.form()
        for key, value in form.items():
            if isinstance(value, str):
                params[key] = value
    return params


def text(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def parse_date(value: str | None, *, default: date | None = None, label: str = "data") -> date:
    if not value:
        if default is not None:
            return default
        raise ValidationError(f"Introdu {label}.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValidationError(
            f"{label[:1].upper()}{label[1:]} trebuie să fie o dată ca 2026-09-29."
        ) from exc


def parse_optional_date(value: str | None, label: str = "data") -> date | None:
    if not value or not value.strip():
        return None
    return parse_date(value, label=label)


def parse_necessity(value: str | None) -> int | None:
    """Return None for an empty field or 'unrated', else the level 1 to 4."""
    if not value or value.strip().lower() in ("", "unrated", "none"):
        return None
    try:
        level = int(value)
    except ValueError as exc:
        raise ValidationError("Nivelul de necesitate trebuie să fie între 1 și 4.") from exc
    if level not in (1, 2, 3, 4):
        raise ValidationError("Nivelul de necesitate trebuie să fie între 1 și 4.")
    return level


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "on", "true", "yes")


def parse_optional_bool(value: str | None) -> bool | None:
    """Return None for an empty filter, True for '1' and False for '0'."""
    if value is None or not value.strip():
        return None
    return value.strip() in ("1", "on", "true", "yes")


def parse_int(value: str | None, label: str) -> int:
    if not value or not value.strip():
        raise ValidationError(f"Introdu {label}.")
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValidationError(
            f"{label[:1].upper()}{label[1:]} trebuie să fie un număr întreg."
        ) from exc


def parse_optional_int(value: str | None, label: str) -> int | None:
    if not value or not value.strip():
        return None
    return parse_int(value, label)
