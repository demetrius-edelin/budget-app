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
    ("Groceries", None, False),
    ("Eating out", None, False),
    ("Fuel & car", None, False),
    ("Housing", ESSENTIAL, False),
    ("Utilities", ESSENTIAL, False),
    ("Health", ESSENTIAL, False),
    ("Transport", None, False),
    ("Subscriptions", None, True),
    ("Shopping", None, False),
    ("Entertainment", None, False),
    ("Personal care", None, False),
    ("Gifts & other", None, False),
    ("Uncategorized", None, False),
]

DEFAULT_SETTINGS: dict[str, str] = {
    "currency": "RON",
    "number_format": "ro-RO",
    "monthly_target_minor": "",
    "fuel_cost_mode": "km",
    "backup_keep_days": "30",
}

DRIVE_METRIC = {
    "key": "drive",
    "name": "Driving",
    "unit": "km",
    "category": "Fuel & car",
    "calculator": "fuel_cost",
}


def seed(session: Session) -> None:
    """Insert the seed rows that do not exist yet."""
    existing = {c.name: c for c in session.scalars(select(Category)).all()}
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

    if session.scalar(select(MetricType).where(MetricType.key == DRIVE_METRIC["key"])) is None:
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
