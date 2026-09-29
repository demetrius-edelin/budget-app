"""List, create and change categories."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from spendtrack.core.errors import NotFoundError, ValidationError
from spendtrack.db.models import Category


def list_categories(session: Session, *, include_archived: bool = False) -> list[Category]:
    query = select(Category).order_by(Category.sort_order, Category.name)
    if not include_archived:
        query = query.where(Category.archived.is_(False))
    return list(session.scalars(query).all())


def get_category(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise NotFoundError(f"Categoria {category_id} nu există.")
    return category


def get_category_by_name(session: Session, name: str) -> Category:
    category = session.scalar(select(Category).where(Category.name == name))
    if category is None:
        raise NotFoundError(f"Categoria {name!r} nu există.")
    return category


def _check_name(session: Session, name: str, *, except_id: int | None = None) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValidationError("Categoria are nevoie de un nume.")
    query = select(Category).where(func.lower(Category.name) == cleaned.lower())
    if except_id is not None:
        query = query.where(Category.id != except_id)
    if session.scalar(query) is not None:
        raise ValidationError(f"Există deja o categorie numită {cleaned!r}.")
    return cleaned


def _check_necessity(value: int | None) -> int | None:
    if value is not None and value not in (1, 2, 3, 4):
        raise ValidationError("Necesitatea implicită trebuie să fie între 1 și 4.")
    return value


def create_category(
    session: Session,
    name: str,
    *,
    default_necessity: int | None = None,
    default_recurring: bool = False,
) -> Category:
    max_order = session.scalar(select(func.max(Category.sort_order))) or 0
    category = Category(
        name=_check_name(session, name),
        default_necessity=_check_necessity(default_necessity),
        default_recurring=default_recurring,
        sort_order=max_order + 1,
    )
    session.add(category)
    session.flush()
    return category


_FIELDS = ("name", "default_necessity", "default_recurring", "sort_order", "archived")


def update_category(session: Session, category_id: int, **changes: Any) -> Category:
    unknown = set(changes) - set(_FIELDS)
    if unknown:
        raise ValidationError(f"Câmpuri necunoscute: {', '.join(sorted(unknown))}.")
    category = get_category(session, category_id)
    if "name" in changes:
        category.name = _check_name(session, changes["name"], except_id=category.id)
    if "default_necessity" in changes:
        category.default_necessity = _check_necessity(changes["default_necessity"])
    if "default_recurring" in changes:
        category.default_recurring = bool(changes["default_recurring"])
    if "sort_order" in changes:
        category.sort_order = int(changes["sort_order"])
    if "archived" in changes:
        category.archived = bool(changes["archived"])
    session.flush()
    return category
