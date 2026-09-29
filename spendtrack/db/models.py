"""SQLAlchemy models. See the specification, section 4."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Return the current time in UTC, with a time zone."""
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Store a timestamp as a UTC ISO-8601 string."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    def process_result_value(self, value: str | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)


class DecimalText(TypeDecorator[Decimal]):
    """Store a decimal number as text, so no precision is lost."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return format(Decimal(value), "f")

    def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    default_necessity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            "default_necessity IS NULL OR default_necessity BETWEEN 1 AND 4",
            name="ck_category_default_necessity",
        ),
    )


class Expense(Base):
    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    necessity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cheaper_alt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cheaper_alt_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cheaper_alt_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="web")
    informational: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    category: Mapped[Category] = relationship(lazy="joined")
    items: Mapped[list[ExpenseItem]] = relationship(
        back_populates="expense", cascade="all, delete-orphan", order_by="ExpenseItem.id"
    )
    metric_entry: Mapped[MetricEntry | None] = relationship(
        back_populates="expense", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_expense_amount_positive"),
        CheckConstraint(
            "necessity IS NULL OR necessity BETWEEN 1 AND 4", name="ck_expense_necessity"
        ),
        CheckConstraint("source IN ('web', 'metric')", name="ck_expense_source"),
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def live_items(self) -> list[ExpenseItem]:
        """Return the items that are not deleted."""
        return [item for item in self.items if item.deleted_at is None]


class ExpenseItem(Base):
    __tablename__ = "expense_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expense.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id"), nullable=True)
    necessity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cheaper_alt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cheaper_alt_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cheaper_alt_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    expense: Mapped[Expense] = relationship(back_populates="items")
    category: Mapped[Category | None] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_item_amount_positive"),
        CheckConstraint("necessity IS NULL OR necessity BETWEEN 1 AND 4", name="ck_item_necessity"),
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MetricType(Base):
    __tablename__ = "metric_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), nullable=False)
    calculator: Mapped[str] = mapped_column(String(80), nullable=False)

    category: Mapped[Category] = relationship(lazy="joined")
    params: Mapped[list[MetricParam]] = relationship(
        back_populates="metric_type", order_by="MetricParam.effective_from"
    )


class MetricParam(Base):
    __tablename__ = "metric_param"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_type_id: Mapped[int] = mapped_column(ForeignKey("metric_type.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    metric_type: Mapped[MetricType] = relationship(back_populates="params")

    __table_args__ = (Index("ix_metric_param_lookup", "metric_type_id", "name", "effective_from"),)


class MetricEntry(Base):
    __tablename__ = "metric_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_type_id: Mapped[int] = mapped_column(ForeignKey("metric_type.id"), nullable=False)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expense.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    params_used: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    metric_type: Mapped[MetricType] = relationship(lazy="joined")
    expense: Mapped[Expense] = relationship(back_populates="metric_entry")

    __table_args__ = (UniqueConstraint("expense_id", name="uq_metric_entry_expense"),)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
