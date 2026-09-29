"""Seed data: categories, the drive metric and the default settings.

The seed is idempotent. Run it on every start.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendtrack.db.models import Category, MetricType, Setting

ESSENTIAL = 1

# (name, default_necessity, default_recurring)
SEED_CATEGORIES: list[tuple[str, int | None, bool]] = [
    ("Alimente", None, False),
    ("Mâncare în oraș", None, False),
    ("Combustibil și mașină", None, False),
    ("Locuință", ESSENTIAL, False),
    ("Utilități", ESSENTIAL, False),
    ("Sănătate", ESSENTIAL, False),
    ("Transport", None, False),
    ("Abonamente", None, True),
    ("Cumpărături", None, False),
    ("Divertisment", None, False),
    ("Îngrijire personală", None, False),
    ("Cadouri și altele", None, False),
    ("Necategorisit", None, False),
]

UNCATEGORIZED = "Necategorisit"
FUEL_CATEGORY = "Combustibil și mașină"

# The first builds seeded English names. The seed renames them once.
RENAMES: dict[str, str] = {
    "Groceries": "Alimente",
    "Eating out": "Mâncare în oraș",
    "Fuel & car": "Combustibil și mașină",
    "Housing": "Locuință",
    "Utilities": "Utilități",
    "Health": "Sănătate",
    "Subscriptions": "Abonamente",
    "Shopping": "Cumpărături",
    "Entertainment": "Divertisment",
    "Personal care": "Îngrijire personală",
    "Gifts & other": "Cadouri și altele",
    "Uncategorized": "Necategorisit",
}

DEFAULT_SETTINGS: dict[str, str] = {
    "currency": "RON",
    "number_format": "ro-RO",
    "monthly_target_minor": "",
    "fuel_cost_mode": "km",
    "backup_keep_days": "30",
}

DRIVE_METRIC = {
    "key": "drive",
    "name": "Condus",
    "unit": "km",
    "category": FUEL_CATEGORY,
    "calculator": "fuel_cost",
}


def seed(session: Session) -> None:
    """Insert the seed rows that do not exist yet. Rename English seed names once."""
    existing = {c.name: c for c in session.scalars(select(Category)).all()}
    for english, romanian in RENAMES.items():
        if english in existing and romanian not in existing:
            existing[english].name = romanian
            existing[romanian] = existing.pop(english)
    session.flush()
    for order, (name, necessity, recurring) in enumerate(SEED_CATEGORIES):
        if name not in existing:
            category = Category(
                name=name,
                default_necessity=necessity,
                default_recurring=recurring,
                sort_order=order,
            )
            session.add(category)
            existing[name] = category
    session.flush()

    drive = session.scalar(select(MetricType).where(MetricType.key == DRIVE_METRIC["key"]))
    if drive is not None and drive.name == "Driving":
        drive.name = DRIVE_METRIC["name"]
    if drive is None:
        session.add(
            MetricType(
                key=DRIVE_METRIC["key"],
                name=DRIVE_METRIC["name"],
                unit=DRIVE_METRIC["unit"],
                category_id=existing[DRIVE_METRIC["category"]].id,
                calculator=DRIVE_METRIC["calculator"],
            )
        )

    present = {s.key for s in session.scalars(select(Setting)).all()}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in present:
            session.add(Setting(key=key, value=value))
    session.flush()
