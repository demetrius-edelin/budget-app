"""Create, edit, itemize, delete and restore expenses. See the specification, section 4."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from spendtrack.core.errors import NotFoundError, ValidationError
from spendtrack.core.money import to_decimal
from spendtrack.db.models import Category, Expense, ExpenseItem, utcnow

NECESSITY_NAMES: dict[int, str] = {
    1: "Esențial",
    2: "Important",
    3: "Util",
    4: "Impuls",
}
UNRATED_NAME = "Neevaluat"
UNSPECIFIED_NAME = "Nespecificat"
DISCRETIONARY_LEVELS = (3, 4)
RADICAL_LEVELS = (2, 3, 4)
IMPULSE = 4
SOURCES = ("web", "metric", "telegram")


class _Unset:
    """Marker for an argument that the caller did not give."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


def necessity_name(level: int | None) -> str:
    if level is None:
        return UNRATED_NAME
    return NECESSITY_NAMES[level]


@dataclass
class ItemInput:
    """One item to add to an expense."""

    description: str
    amount_minor: int
    category_id: int | None = None
    necessity: int | None = None
    cheaper_alt: bool = False
    cheaper_alt_minor: int | None = None
    cheaper_alt_note: str | None = None


@dataclass(frozen=True)
class Line:
    """One breakdown line: an item, or the Unspecified remainder of an expense."""

    expense_id: int
    item_id: int | None
    occurred_on: date
    description: str
    amount_minor: int
    category_id: int
    category_name: str
    necessity: int | None
    cheaper_alt: bool
    cheaper_alt_minor: int | None
    cheaper_alt_note: str | None
    recurring: bool
    is_remainder: bool
    source: str

    @property
    def potential_saving_minor(self) -> int:
        """Return the amount minus the cheaper price, when that price is set and lower."""
        if (
            self.cheaper_alt
            and self.cheaper_alt_minor is not None
            and self.cheaper_alt_minor < self.amount_minor
        ):
            return self.amount_minor - self.cheaper_alt_minor
        return 0

    @property
    def necessity_name(self) -> str:
        return necessity_name(self.necessity)


def _money(minor: int) -> str:
    return f"{to_decimal(minor):.2f}"


def _check_necessity(value: int | None) -> int | None:
    if value is None:
        return None
    if value not in NECESSITY_NAMES:
        raise ValidationError("Nivelul de necesitate trebuie să fie între 1 și 4.")
    return value


def _normalize_cheaper(
    cheaper_alt: bool, cheaper_alt_minor: int | None, cheaper_alt_note: str | None
) -> tuple[bool, int | None, str | None]:
    """Apply the rule: a cheaper price or note sets the flag, and no flag clears both."""
    if cheaper_alt_minor is not None and cheaper_alt_minor <= 0:
        raise ValidationError("Prețul mai ieftin trebuie să fie mai mare decât zero.")
    note = (cheaper_alt_note or "").strip() or None
    if cheaper_alt_minor is not None or note is not None:
        cheaper_alt = True
    if not cheaper_alt:
        return False, None, None
    return True, cheaper_alt_minor, note


def get_category(session: Session, category_id: int) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise NotFoundError(f"Categoria {category_id} nu există.")
    return category


def get_expense(session: Session, expense_id: int, *, include_deleted: bool = False) -> Expense:
    """Return the expense with its items, or raise NotFoundError."""
    expense = session.scalar(
        select(Expense).options(selectinload(Expense.items)).where(Expense.id == expense_id)
    )
    if expense is None or (expense.deleted_at is not None and not include_deleted):
        raise NotFoundError(f"Cheltuiala #{expense_id} nu există.")
    return expense


def create_expense(
    session: Session,
    *,
    occurred_on: date,
    amount_minor: int,
    category_id: int,
    description: str | None = None,
    necessity: int | None = UNSET,
    cheaper_alt: bool = False,
    cheaper_alt_minor: int | None = None,
    cheaper_alt_note: str | None = None,
    recurring: bool = UNSET,
    source: str = "web",
    informational: bool = False,
) -> Expense:
    """Create an expense. UNSET necessity or recurring takes the category default."""
    if amount_minor <= 0:
        raise ValidationError("Suma trebuie să fie mai mare decât zero.")
    if source not in SOURCES:
        raise ValidationError(f"Sursă necunoscută {source!r}.")
    category = get_category(session, category_id)
    if necessity is UNSET:
        necessity = category.default_necessity
    if recurring is UNSET:
        recurring = category.default_recurring
    cheaper_alt, cheaper_alt_minor, cheaper_alt_note = _normalize_cheaper(
        cheaper_alt, cheaper_alt_minor, cheaper_alt_note
    )
    expense = Expense(
        occurred_on=occurred_on,
        amount_minor=amount_minor,
        category_id=category.id,
        description=(description or "").strip() or None,
        necessity=_check_necessity(necessity),
        cheaper_alt=cheaper_alt,
        cheaper_alt_minor=cheaper_alt_minor,
        cheaper_alt_note=cheaper_alt_note,
        recurring=bool(recurring),
        source=source,
        informational=informational,
    )
    session.add(expense)
    session.flush()
    session.refresh(expense)
    return expense


def items_total(expense: Expense) -> int:
    """Return the sum of the items that are not deleted."""
    return sum(item.amount_minor for item in expense.live_items)


def remainder_minor(expense: Expense) -> int:
    return expense.amount_minor - items_total(expense)


_EXPENSE_FIELDS = (
    "occurred_on",
    "amount_minor",
    "category_id",
    "description",
    "necessity",
    "cheaper_alt",
    "cheaper_alt_minor",
    "cheaper_alt_note",
    "recurring",
)


def update_expense(session: Session, expense_id: int, **changes: Any) -> Expense:
    """Change the given fields of an expense. Reject an amount below the item total."""
    unknown = set(changes) - set(_EXPENSE_FIELDS)
    if unknown:
        raise ValidationError(f"Câmpuri necunoscute: {', '.join(sorted(unknown))}.")
    expense = get_expense(session, expense_id)

    if "amount_minor" in changes:
        amount = changes["amount_minor"]
        if expense.source == "metric":
            raise ValidationError(
                "Suma unui drum nu se poate modifica. Șterge intrarea și adaug-o din nou."
            )
        if amount <= 0:
            raise ValidationError("Suma trebuie să fie mai mare decât zero.")
        total = items_total(expense)
        if amount < total:
            raise ValidationError(
                f"Suma este sub totalul articolelor de {_money(total)}."
                " Modifică mai întâi articolele."
            )
        expense.amount_minor = amount

    if "category_id" in changes:
        expense.category_id = get_category(session, changes["category_id"]).id
    if "occurred_on" in changes:
        expense.occurred_on = changes["occurred_on"]
    if "description" in changes:
        expense.description = (changes["description"] or "").strip() or None
    if "necessity" in changes:
        expense.necessity = _check_necessity(changes["necessity"])
    if "recurring" in changes:
        expense.recurring = bool(changes["recurring"])

    if any(key in changes for key in ("cheaper_alt", "cheaper_alt_minor", "cheaper_alt_note")):
        flag = changes.get("cheaper_alt", expense.cheaper_alt)
        minor = changes.get("cheaper_alt_minor", expense.cheaper_alt_minor)
        note = changes.get("cheaper_alt_note", expense.cheaper_alt_note)
        if "cheaper_alt" in changes and not flag:
            minor, note = None, None
        expense.cheaper_alt, expense.cheaper_alt_minor, expense.cheaper_alt_note = (
            _normalize_cheaper(flag, minor, note)
        )

    session.flush()
    session.refresh(expense)
    return expense


def delete_expense(session: Session, expense_id: int) -> Expense:
    """Soft-delete an expense. Its items and its metric entry follow it."""
    expense = get_expense(session, expense_id)
    expense.deleted_at = utcnow()
    session.flush()
    return expense


def restore_expense(session: Session, expense_id: int) -> Expense:
    expense = get_expense(session, expense_id, include_deleted=True)
    expense.deleted_at = None
    session.flush()
    return expense


def add_items(session: Session, expense_id: int, items: list[ItemInput]) -> list[ExpenseItem]:
    """Add items to an expense. Reject all of them if their sum exceeds the remainder."""
    expense = get_expense(session, expense_id)
    if not items:
        raise ValidationError("Adaugă cel puțin un articol.")
    for item in items:
        if not item.description.strip():
            raise ValidationError("Fiecare articol are nevoie de o descriere.")
        if item.amount_minor <= 0:
            raise ValidationError("Suma fiecărui articol trebuie să fie mai mare decât zero.")
    new_total = items_total(expense) + sum(item.amount_minor for item in items)
    if new_total > expense.amount_minor:
        raise ValidationError(
            f"Articolele {_money(new_total)} depășesc suma cheltuielii"
            f" {_money(expense.amount_minor)}. Modifică mai întâi totalul."
        )
    created: list[ExpenseItem] = []
    for item in items:
        if item.category_id is not None:
            get_category(session, item.category_id)
        cheaper_alt, cheaper_alt_minor, cheaper_alt_note = _normalize_cheaper(
            item.cheaper_alt, item.cheaper_alt_minor, item.cheaper_alt_note
        )
        row = ExpenseItem(
            expense_id=expense.id,
            description=item.description.strip(),
            amount_minor=item.amount_minor,
            category_id=item.category_id,
            necessity=_check_necessity(item.necessity),
            cheaper_alt=cheaper_alt,
            cheaper_alt_minor=cheaper_alt_minor,
            cheaper_alt_note=cheaper_alt_note,
        )
        session.add(row)
        expense.items.append(row)
        created.append(row)
    session.flush()
    for row in created:
        session.refresh(row)
    return created


def get_item(session: Session, item_id: int, *, include_deleted: bool = False) -> ExpenseItem:
    item = session.get(ExpenseItem, item_id)
    if item is None or (item.deleted_at is not None and not include_deleted):
        raise NotFoundError(f"Articolul {item_id} nu există.")
    if item.expense.deleted_at is not None and not include_deleted:
        raise NotFoundError(f"Articolul {item_id} aparține unei cheltuieli șterse.")
    return item


_ITEM_FIELDS = (
    "description",
    "amount_minor",
    "category_id",
    "necessity",
    "cheaper_alt",
    "cheaper_alt_minor",
    "cheaper_alt_note",
)


def update_item(session: Session, item_id: int, **changes: Any) -> ExpenseItem:
    """Change the given fields of an item. Reject a sum above the expense amount."""
    unknown = set(changes) - set(_ITEM_FIELDS)
    if unknown:
        raise ValidationError(f"Câmpuri necunoscute: {', '.join(sorted(unknown))}.")
    item = get_item(session, item_id)
    expense = item.expense

    if "amount_minor" in changes:
        amount = changes["amount_minor"]
        if amount <= 0:
            raise ValidationError("Suma articolului trebuie să fie mai mare decât zero.")
        others = items_total(expense) - item.amount_minor
        if others + amount > expense.amount_minor:
            raise ValidationError(
                f"Articolele {_money(others + amount)} depășesc suma cheltuielii"
                f" {_money(expense.amount_minor)}. Modifică mai întâi totalul."
            )
        item.amount_minor = amount

    if "description" in changes:
        description = (changes["description"] or "").strip()
        if not description:
            raise ValidationError("Fiecare articol are nevoie de o descriere.")
        item.description = description
    if "category_id" in changes:
        category_id = changes["category_id"]
        item.category_id = None if category_id is None else get_category(session, category_id).id
    if "necessity" in changes:
        item.necessity = _check_necessity(changes["necessity"])

    if any(key in changes for key in ("cheaper_alt", "cheaper_alt_minor", "cheaper_alt_note")):
        flag = changes.get("cheaper_alt", item.cheaper_alt)
        minor = changes.get("cheaper_alt_minor", item.cheaper_alt_minor)
        note = changes.get("cheaper_alt_note", item.cheaper_alt_note)
        if "cheaper_alt" in changes and not flag:
            minor, note = None, None
        item.cheaper_alt, item.cheaper_alt_minor, item.cheaper_alt_note = _normalize_cheaper(
            flag, minor, note
        )

    session.flush()
    session.refresh(item)
    return item


def delete_item(session: Session, item_id: int) -> ExpenseItem:
    item = get_item(session, item_id)
    item.deleted_at = utcnow()
    session.flush()
    return item


def restore_item(session: Session, item_id: int) -> ExpenseItem:
    item = get_item(session, item_id, include_deleted=True)
    if item.expense.deleted_at is not None:
        raise ValidationError("Restaurează mai întâi cheltuiala.")
    others = items_total(item.expense)
    if others + item.amount_minor > item.expense.amount_minor:
        raise ValidationError("Articolul nu mai încape în suma cheltuielii.")
    item.deleted_at = None
    session.flush()
    return item


def expense_lines(expense: Expense) -> list[Line]:
    """Return the breakdown lines of an expense: its items plus the Unspecified remainder."""
    lines: list[Line] = []
    for item in expense.live_items:
        category = item.category or expense.category
        lines.append(
            Line(
                expense_id=expense.id,
                item_id=item.id,
                occurred_on=expense.occurred_on,
                description=item.description,
                amount_minor=item.amount_minor,
                category_id=category.id,
                category_name=category.name,
                necessity=item.necessity if item.necessity is not None else expense.necessity,
                cheaper_alt=item.cheaper_alt,
                cheaper_alt_minor=item.cheaper_alt_minor,
                cheaper_alt_note=item.cheaper_alt_note,
                recurring=expense.recurring,
                is_remainder=False,
                source=expense.source,
            )
        )
    rest = remainder_minor(expense)
    if rest > 0:
        description = UNSPECIFIED_NAME if lines else (expense.description or UNSPECIFIED_NAME)
        lines.append(
            Line(
                expense_id=expense.id,
                item_id=None,
                occurred_on=expense.occurred_on,
                description=description,
                amount_minor=rest,
                category_id=expense.category.id,
                category_name=expense.category.name,
                necessity=expense.necessity,
                cheaper_alt=expense.cheaper_alt,
                cheaper_alt_minor=expense.cheaper_alt_minor,
                cheaper_alt_note=expense.cheaper_alt_note,
                recurring=expense.recurring,
                is_remainder=True,
                source=expense.source,
            )
        )
    return lines


def list_expenses(
    session: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    category_id: int | None = None,
    necessity: int | str | None = None,
    cheaper: bool | None = None,
    recurring: bool | None = None,
    search: str | None = None,
    include_deleted: bool = False,
    include_informational: bool = True,
    limit: int | None = None,
) -> list[Expense]:
    """Return expenses, newest first. The necessity filter accepts 1 to 4 or 'unrated'."""
    query = select(Expense).options(selectinload(Expense.items))
    if not include_deleted:
        query = query.where(Expense.deleted_at.is_(None))
    if not include_informational:
        query = query.where(Expense.informational.is_(False))
    if start is not None:
        query = query.where(Expense.occurred_on >= start)
    if end is not None:
        query = query.where(Expense.occurred_on <= end)
    if category_id is not None:
        query = query.where(Expense.category_id == category_id)
    if necessity == "unrated":
        query = query.where(Expense.necessity.is_(None))
    elif isinstance(necessity, int):
        query = query.where(Expense.necessity == necessity)
    if cheaper is not None:
        query = query.where(Expense.cheaper_alt.is_(cheaper))
    if recurring is not None:
        query = query.where(Expense.recurring.is_(recurring))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(Expense.description.ilike(pattern))
    query = query.order_by(Expense.occurred_on.desc(), Expense.id.desc())
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query).all())


def review_queue(session: Session) -> list[Expense]:
    """Return the unrated expenses, oldest first."""
    query = (
        select(Expense)
        .options(selectinload(Expense.items))
        .where(Expense.deleted_at.is_(None), Expense.necessity.is_(None))
        .order_by(Expense.occurred_on.asc(), Expense.id.asc())
    )
    return list(session.scalars(query).all())


def unrated_count(session: Session) -> int:
    return len(review_queue(session))
