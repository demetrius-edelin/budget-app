from datetime import date

import pytest
from sqlalchemy.orm import Session

from spendtrack.core import expenses as core
from spendtrack.core.errors import NotFoundError, ValidationError
from spendtrack.core.expenses import ItemInput
from tests.conftest import TODAY


def test_case_1_groceries_100(session: Session, category) -> None:
    expense = core.create_expense(
        session, occurred_on=TODAY, amount_minor=10000, category_id=category("Groceries")
    )
    assert expense.id == 1
    assert expense.category.name == "Groceries"
    assert expense.amount_minor == 10000
    assert expense.occurred_on == TODAY
    assert expense.necessity is None
    assert expense.source == "web"


def test_case_2_impulse_with_cheaper_price(session: Session, category) -> None:
    expense = core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=1850,
        category_id=category("Eating out"),
        necessity=4,
        cheaper_alt=True,
        cheaper_alt_minor=800,
    )
    (line,) = core.expense_lines(expense)
    assert expense.necessity == 4
    assert expense.cheaper_alt_minor == 800
    assert line.potential_saving_minor == 1050


def test_case_3_transport_yesterday(session: Session, category) -> None:
    expense = core.create_expense(
        session, occurred_on=date(2026, 9, 28), amount_minor=3500, category_id=category("Transport")
    )
    assert expense.occurred_on == date(2026, 9, 28)


def test_case_4_housing_takes_the_category_default(session: Session, category) -> None:
    expense = core.create_expense(
        session, occurred_on=TODAY, amount_minor=250000, category_id=category("Housing")
    )
    assert expense.necessity == 1


def test_explicit_unrated_beats_the_category_default(session: Session, category) -> None:
    expense = core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=250000,
        category_id=category("Housing"),
        necessity=None,
    )
    assert expense.necessity is None


def test_subscriptions_default_to_recurring(session: Session, category) -> None:
    expense = core.create_expense(
        session, occurred_on=TODAY, amount_minor=5000, category_id=category("Subscriptions")
    )
    assert expense.recurring is True


def test_case_6_zero_amount_is_rejected(session: Session, category) -> None:
    with pytest.raises(ValidationError):
        core.create_expense(
            session, occurred_on=TODAY, amount_minor=0, category_id=category("Groceries")
        )


def _groceries(session: Session, category) -> int:
    return core.create_expense(
        session, occurred_on=TODAY, amount_minor=10000, category_id=category("Groceries")
    ).id


def test_case_11_add_item_keeps_the_total(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    core.add_items(session, expense_id, [ItemInput("Wine", 5000, necessity=3)])
    expense = core.get_expense(session, expense_id)
    assert expense.amount_minor == 10000
    lines = core.expense_lines(expense)
    assert [(line.description, line.amount_minor, line.necessity) for line in lines] == [
        ("Wine", 5000, 3),
        ("Unspecified", 5000, None),
    ]


def test_case_12_items_above_the_total_are_rejected(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    with pytest.raises(ValidationError, match="exceed"):
        core.add_items(session, expense_id, [ItemInput("Wine", 5000), ItemInput("Cheese", 6000)])
    assert core.get_expense(session, expense_id).live_items == []


def test_case_13_amount_below_items_is_rejected(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    core.add_items(session, expense_id, [ItemInput("Wine", 5000, necessity=3)])
    with pytest.raises(ValidationError, match="below the item total of 50.00"):
        core.update_expense(session, expense_id, amount_minor=4000)
    assert core.get_expense(session, expense_id).amount_minor == 10000


def test_case_14_item_with_its_own_category(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    core.add_items(
        session, expense_id, [ItemInput("Coffee", 1000, category_id=category("Eating out"))]
    )
    lines = core.expense_lines(core.get_expense(session, expense_id))
    assert [(line.description, line.amount_minor, line.category_name) for line in lines] == [
        ("Coffee", 1000, "Eating out"),
        ("Unspecified", 9000, "Groceries"),
    ]


def test_case_17_delete_then_restore(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    core.delete_expense(session, expense_id)
    assert core.list_expenses(session) == []
    with pytest.raises(NotFoundError):
        core.get_expense(session, expense_id)
    core.restore_expense(session, expense_id)
    assert [e.id for e in core.list_expenses(session)] == [expense_id]


def test_remainder_of_zero_is_dropped(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    core.add_items(session, expense_id, [ItemInput("Wine", 6000), ItemInput("Cheese", 4000)])
    lines = core.expense_lines(core.get_expense(session, expense_id))
    assert [line.description for line in lines] == ["Wine", "Cheese"]


def test_item_inherits_the_expense_rating_and_recurring(session: Session, category) -> None:
    expense = core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=10000,
        category_id=category("Groceries"),
        necessity=1,
        recurring=True,
    )
    core.add_items(session, expense.id, [ItemInput("Wine", 5000)])
    wine, rest = core.expense_lines(core.get_expense(session, expense.id))
    assert (wine.necessity, wine.recurring) == (1, True)
    assert (rest.necessity, rest.recurring) == (1, True)


def test_update_item_amount_checks_the_total(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    (wine,) = core.add_items(session, expense_id, [ItemInput("Wine", 5000)])
    core.update_item(session, wine.id, amount_minor=10000)
    with pytest.raises(ValidationError):
        core.update_item(session, wine.id, amount_minor=10001)


def test_delete_item_frees_the_remainder(session: Session, category) -> None:
    expense_id = _groceries(session, category)
    (wine,) = core.add_items(session, expense_id, [ItemInput("Wine", 5000)])
    core.delete_item(session, wine.id)
    expense = core.get_expense(session, expense_id)
    assert core.remainder_minor(expense) == 10000
    core.restore_item(session, wine.id)
    assert core.remainder_minor(core.get_expense(session, expense_id)) == 5000


def test_cheaper_price_sets_the_flag_and_no_flag_clears_it(session: Session, category) -> None:
    expense = core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=10000,
        category_id=category("Groceries"),
        cheaper_alt_minor=8000,
    )
    assert expense.cheaper_alt is True
    core.update_expense(session, expense.id, cheaper_alt=False)
    expense = core.get_expense(session, expense.id)
    assert (expense.cheaper_alt, expense.cheaper_alt_minor) == (False, None)


def test_list_filters(session: Session, category) -> None:
    core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=1000,
        category_id=category("Groceries"),
        description="Bread",
        necessity=1,
    )
    core.create_expense(
        session,
        occurred_on=TODAY,
        amount_minor=2000,
        category_id=category("Eating out"),
        description="Lunch",
        cheaper_alt=True,
    )
    assert len(core.list_expenses(session, necessity="unrated")) == 1
    assert len(core.list_expenses(session, necessity=1)) == 1
    assert len(core.list_expenses(session, cheaper=True)) == 1
    assert len(core.list_expenses(session, search="bre")) == 1
    assert len(core.list_expenses(session, category_id=category("Eating out"))) == 1
    assert core.unrated_count(session) == 1
