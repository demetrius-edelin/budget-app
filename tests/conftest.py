"""Shared fixtures. The fixture state follows the specification, section 10."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from spendtrack.core import metrics
from spendtrack.core.categories import get_category_by_name
from spendtrack.db.models import Base
from spendtrack.db.seed import seed
from spendtrack.db.session import make_engine, make_session_factory

TODAY = date(2026, 9, 29)  # a Tuesday
PARAMS_FROM = date(2026, 9, 1)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        seed(db)
        metrics.set_param(db, "drive", "consumption_l_per_100km", Decimal("7.2"), PARAMS_FROM)
        metrics.set_param(db, "drive", "fuel_price_per_l", Decimal("8.28"), PARAMS_FROM)
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def category(session: Session):
    """Return a function that maps a category name to its id."""

    def lookup(name: str) -> int:
        return get_category_by_name(session, name).id

    return lookup
