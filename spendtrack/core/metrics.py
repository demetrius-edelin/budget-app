"""Metric entries: convert a measured quantity into an expense. See the specification, section 5."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from spendtrack.core import settings as settings_core
from spendtrack.core.errors import MissingParameterError, NotFoundError, ValidationError
from spendtrack.core.expenses import UNSET, create_expense
from spendtrack.core.money import format_decimal, to_minor
from spendtrack.db.models import Expense, MetricEntry, MetricParam, MetricType

Calculator = Callable[[Decimal, dict[str, Decimal]], Decimal]


def fuel_cost(quantity: Decimal, params: dict[str, Decimal]) -> Decimal:
    """cost = km × consumption (L/100 km) / 100 × fuel price (RON/L)"""
    return quantity * params["consumption_l_per_100km"] / Decimal(100) * params["fuel_price_per_l"]


CALCULATORS: dict[str, Calculator] = {"fuel_cost": fuel_cost}

# calculator name -> the parameter names it needs, in the order of the calculation text
CALCULATOR_PARAMS: dict[str, list[str]] = {
    "fuel_cost": ["consumption_l_per_100km", "fuel_price_per_l"],
}

# parameter name -> (label, unit)
PARAM_LABELS: dict[str, tuple[str, str]] = {
    "consumption_l_per_100km": ("Consumption", "L/100 km"),
    "fuel_price_per_l": ("Fuel price", "RON/L"),
}


def param_label(name: str) -> tuple[str, str]:
    return PARAM_LABELS.get(name, (name, ""))


def list_metric_types(session: Session) -> list[MetricType]:
    return list(session.scalars(select(MetricType).order_by(MetricType.id)).all())


def get_metric_type(session: Session, key: str) -> MetricType:
    metric_type = session.scalar(select(MetricType).where(MetricType.key == key))
    if metric_type is None:
        raise NotFoundError(f"Metric {key!r} does not exist.")
    return metric_type


def param_names(metric_type: MetricType) -> list[str]:
    try:
        return CALCULATOR_PARAMS[metric_type.calculator]
    except KeyError as exc:
        raise ValidationError(f"Unknown calculator {metric_type.calculator!r}.") from exc


def param_in_force(
    session: Session, metric_type_id: int, name: str, on_date: date
) -> MetricParam | None:
    """Return the latest parameter row with effective_from on or before the date."""
    query = (
        select(MetricParam)
        .where(
            MetricParam.metric_type_id == metric_type_id,
            MetricParam.name == name,
            MetricParam.effective_from <= on_date,
        )
        .order_by(MetricParam.effective_from.desc(), MetricParam.id.desc())
        .limit(1)
    )
    return session.scalar(query)


def param_history(session: Session, metric_key: str) -> list[MetricParam]:
    metric_type = get_metric_type(session, metric_key)
    query = (
        select(MetricParam)
        .where(MetricParam.metric_type_id == metric_type.id)
        .order_by(MetricParam.name, MetricParam.effective_from.desc(), MetricParam.id.desc())
    )
    return list(session.scalars(query).all())


def set_param(
    session: Session, metric_key: str, name: str, value: Decimal, effective_from: date
) -> MetricParam:
    """Add a dated parameter value. Earlier entries keep the value in force on their date."""
    metric_type = get_metric_type(session, metric_key)
    if name not in param_names(metric_type):
        raise ValidationError(f"Unknown parameter {name!r} for {metric_type.name}.")
    if value <= 0:
        raise ValidationError(f"The {param_label(name)[0].lower()} must be greater than zero.")
    row = MetricParam(
        metric_type_id=metric_type.id, name=name, value=value, effective_from=effective_from
    )
    session.add(row)
    session.flush()
    return row


def delete_param(session: Session, param_id: int) -> None:
    row = session.get(MetricParam, param_id)
    if row is None:
        raise NotFoundError(f"Parameter row {param_id} does not exist.")
    session.delete(row)
    session.flush()


@dataclass(frozen=True)
class MetricQuote:
    """The result of a metric calculation, before or after the save."""

    metric_type: MetricType
    occurred_on: date
    quantity: Decimal
    params_used: dict[str, dict[str, Any]]
    amount_minor: int
    description: str
    calculation: str
    informational: bool


def _describe(metric_type: MetricType, quantity: Decimal) -> str:
    verb = metric_type.key[:1].upper() + metric_type.key[1:]
    return f"{verb} {format_decimal(quantity)} {metric_type.unit}"


def quote(
    session: Session,
    *,
    metric_key: str,
    occurred_on: date,
    quantity: Decimal,
    overrides: dict[str, Decimal] | None = None,
) -> MetricQuote:
    """Compute the cost of a metric entry without a save."""
    if quantity <= 0:
        raise ValidationError("The quantity must be greater than zero.")
    metric_type = get_metric_type(session, metric_key)
    calculator = CALCULATORS.get(metric_type.calculator)
    if calculator is None:
        raise ValidationError(f"Unknown calculator {metric_type.calculator!r}.")
    overrides = overrides or {}
    params: dict[str, Decimal] = {}
    params_used: dict[str, dict[str, Any]] = {}
    parts: list[str] = [f"{format_decimal(quantity)} {metric_type.unit}"]
    for name in param_names(metric_type):
        label, unit = param_label(name)
        if name in overrides and overrides[name] is not None:
            value = Decimal(overrides[name])
            if value <= 0:
                raise ValidationError(f"The {label.lower()} must be greater than zero.")
            params_used[name] = {"value": format_decimal(value), "override": True}
        else:
            row = param_in_force(session, metric_type.id, name, occurred_on)
            if row is None:
                raise MissingParameterError(name, label)
            value = row.value
            params_used[name] = {"value": format_decimal(value), "override": False}
        params[name] = value
        parts.append(f"{format_decimal(value)} {unit}".strip())
    amount_minor = to_minor(calculator(quantity, params))
    if amount_minor <= 0:
        raise ValidationError("The computed cost is zero. Check the parameters.")
    informational = settings_core.fuel_cost_mode(session) == "receipts"
    return MetricQuote(
        metric_type=metric_type,
        occurred_on=occurred_on,
        quantity=quantity,
        params_used=params_used,
        amount_minor=amount_minor,
        description=_describe(metric_type, quantity),
        calculation=" × ".join(parts),
        informational=informational,
    )


def create_metric_entry(
    session: Session,
    *,
    metric_key: str,
    occurred_on: date,
    quantity: Decimal,
    overrides: dict[str, Decimal] | None = None,
    description: str | None = None,
    necessity: int | None = UNSET,
    cheaper_alt: bool = False,
    cheaper_alt_minor: int | None = None,
    cheaper_alt_note: str | None = None,
    recurring: bool = UNSET,
) -> MetricEntry:
    """Save a metric entry and its generated expense.

    The expense description is the automatic text, for example "Drive 42 km".
    An optional description from the owner is appended after a separator.
    """
    result = quote(
        session,
        metric_key=metric_key,
        occurred_on=occurred_on,
        quantity=quantity,
        overrides=overrides,
    )
    text = result.description
    note = (description or "").strip()
    if note:
        text = f"{text} · {note}"
    expense = create_expense(
        session,
        occurred_on=occurred_on,
        amount_minor=result.amount_minor,
        category_id=result.metric_type.category_id,
        description=text,
        necessity=necessity,
        cheaper_alt=cheaper_alt,
        cheaper_alt_minor=cheaper_alt_minor,
        cheaper_alt_note=cheaper_alt_note,
        recurring=recurring,
        source="metric",
        informational=result.informational,
    )
    entry = MetricEntry(
        metric_type_id=result.metric_type.id,
        expense_id=expense.id,
        quantity=quantity,
        params_used=result.params_used,
    )
    session.add(entry)
    session.flush()
    session.refresh(entry)
    return entry


def entry_for_expense(session: Session, expense: Expense) -> MetricEntry | None:
    return session.scalar(select(MetricEntry).where(MetricEntry.expense_id == expense.id))


def calculation_text(entry: MetricEntry) -> str:
    """Rebuild the calculation text of a saved entry from its snapshot."""
    parts = [f"{format_decimal(entry.quantity)} {entry.metric_type.unit}"]
    for name in param_names(entry.metric_type):
        used = entry.params_used.get(name)
        if used is None:
            continue
        unit = param_label(name)[1]
        parts.append(f"{used['value']} {unit}".strip())
    return " × ".join(parts)
