from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from spendtrack.core import expenses as expenses_core
from spendtrack.core import metrics, reports
from spendtrack.core import settings as settings_core
from spendtrack.core.errors import MissingParameterError, ValidationError
from spendtrack.db.models import MetricEntry
from tests.conftest import TODAY


def test_case_7_drive_42_km(session: Session) -> None:
    entry = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    expense = entry.expense
    assert expense.amount_minor == 2504
    assert expense.category.name == "Combustibil și mașină"
    assert expense.description == "Condus 42 km"
    assert expense.source == "metric"
    assert expense.informational is False
    assert metrics.calculation_text(entry) == "42 km × 7.2 L/100 km × 8.28 RON/L"


def test_case_8_overrides_apply_to_that_entry_only(session: Session) -> None:
    entry = metrics.create_metric_entry(
        session,
        metric_key="drive",
        occurred_on=TODAY,
        quantity=Decimal("42"),
        overrides={"consumption_l_per_100km": Decimal("6.5"), "fuel_price_per_l": Decimal("7.99")},
    )
    assert entry.expense.amount_minor == 2181
    assert entry.params_used == {
        "consumption_l_per_100km": {"value": "6.5", "override": True},
        "fuel_price_per_l": {"value": "7.99", "override": True},
    }
    metric_type = metrics.get_metric_type(session, "drive")
    assert metrics.param_in_force(session, metric_type.id, "fuel_price_per_l", TODAY).value == (
        Decimal("8.28")
    )
    again = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    assert again.expense.amount_minor == 2504


def test_case_9_missing_parameter_saves_nothing(session: Session) -> None:
    metrics.set_param(session, "drive", "consumption_l_per_100km", Decimal("7.2"), date(2026, 8, 1))
    with pytest.raises(
        MissingParameterError, match="Setează mai întâi prețul combustibilului în Setări."
    ):
        metrics.quote(
            session, metric_key="drive", occurred_on=date(2026, 8, 15), quantity=Decimal("42")
        )
    with pytest.raises(MissingParameterError):
        metrics.create_metric_entry(
            session, metric_key="drive", occurred_on=date(2026, 8, 15), quantity=Decimal("42")
        )
    assert session.query(MetricEntry).count() == 0
    assert expenses_core.list_expenses(session) == []


def test_case_10_a_new_price_never_changes_earlier_dates(session: Session) -> None:
    metrics.set_param(session, "drive", "fuel_price_per_l", Decimal("8.50"), TODAY)
    earlier = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=date(2026, 9, 27), quantity=Decimal("42")
    )
    assert earlier.expense.amount_minor == 2504
    today = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    assert today.expense.amount_minor == 2570  # 42 × 0.072 × 8.50 = 25.704


def test_case_18_delete_and_restore_a_metric_expense(session: Session) -> None:
    entry = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    expenses_core.delete_expense(session, entry.expense_id)
    assert reports.total_between(session, TODAY, TODAY) == 0
    assert expenses_core.list_expenses(session) == []
    expenses_core.restore_expense(session, entry.expense_id)
    restored = expenses_core.get_expense(session, entry.expense_id)
    assert metrics.entry_for_expense(session, restored) is not None
    assert reports.total_between(session, TODAY, TODAY) == 2504


def test_case_19_receipts_mode_makes_drive_entries_informational(
    session: Session, category
) -> None:
    settings_core.set_fuel_cost_mode(session, "receipts")
    entry = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    expenses_core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=25000,
        category_id=category("Combustibil și mașină"),
    )
    assert entry.expense.amount_minor == 2504
    assert entry.expense.informational is True
    assert reports.total_between(session, TODAY, TODAY) == 25000


def test_case_20_a_mode_change_keeps_existing_entries(session: Session) -> None:
    entry = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    settings_core.set_fuel_cost_mode(session, "receipts")
    assert expenses_core.get_expense(session, entry.expense_id).informational is False
    assert reports.total_between(session, TODAY, TODAY) == 2504


def test_metric_amount_is_read_only(session: Session) -> None:
    entry = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("42")
    )
    with pytest.raises(ValidationError, match="nu se poate modifica"):
        expenses_core.update_expense(session, entry.expense_id, amount_minor=100)


def test_quantity_with_decimals(session: Session) -> None:
    result = metrics.quote(session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("12.5"))
    assert result.description == "Condus 12.5 km"
    assert result.amount_minor == 745  # 12.5 × 0.072 × 8.28 = 7.452


def test_set_param_rejects_unknown_names(session: Session) -> None:
    with pytest.raises(ValidationError):
        metrics.set_param(session, "drive", "tyre_pressure", Decimal("2"), TODAY)


def test_description_is_appended_to_the_automatic_text(session: Session) -> None:
    entry = metrics.create_metric_entry(
        session,
        metric_key="drive",
        occurred_on=TODAY,
        quantity=Decimal("42"),
        description="  Trip to the airport ",
    )
    assert entry.expense.description == "Condus 42 km · Trip to the airport"
    plain = metrics.create_metric_entry(
        session, metric_key="drive", occurred_on=TODAY, quantity=Decimal("10"), description="  "
    )
    assert plain.expense.description == "Condus 10 km"
