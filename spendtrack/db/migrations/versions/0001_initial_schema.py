"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-29 14:39:35.108042
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("default_necessity", sa.Integer(), nullable=True),
        sa.Column("default_recurring", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "default_necessity IS NULL OR default_necessity BETWEEN 1 AND 4",
            name="ck_category_default_necessity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "setting",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "expense",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("necessity", sa.Integer(), nullable=True),
        sa.Column("cheaper_alt", sa.Boolean(), nullable=False),
        sa.Column("cheaper_alt_minor", sa.Integer(), nullable=True),
        sa.Column("cheaper_alt_note", sa.Text(), nullable=True),
        sa.Column("recurring", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("informational", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.String(length=32), nullable=True),
        sa.CheckConstraint("source IN ('web', 'metric')", name="ck_expense_source"),
        sa.CheckConstraint("amount_minor > 0", name="ck_expense_amount_positive"),
        sa.CheckConstraint(
            "necessity IS NULL OR necessity BETWEEN 1 AND 4", name="ck_expense_necessity"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("expense", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_expense_occurred_on"), ["occurred_on"], unique=False)

    op.create_table(
        "metric_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("calculator", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "expense_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("necessity", sa.Integer(), nullable=True),
        sa.Column("cheaper_alt", sa.Boolean(), nullable=False),
        sa.Column("cheaper_alt_minor", sa.Integer(), nullable=True),
        sa.Column("cheaper_alt_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.String(length=32), nullable=True),
        sa.CheckConstraint("amount_minor > 0", name="ck_item_amount_positive"),
        sa.CheckConstraint(
            "necessity IS NULL OR necessity BETWEEN 1 AND 4", name="ck_item_necessity"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
        ),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expense.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("expense_item", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_expense_item_expense_id"), ["expense_id"], unique=False
        )

    op.create_table(
        "metric_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metric_type_id", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.String(length=32), nullable=False),
        sa.Column("params_used", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expense.id"],
        ),
        sa.ForeignKeyConstraint(
            ["metric_type_id"],
            ["metric_type.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expense_id", name="uq_metric_entry_expense"),
    )
    op.create_table(
        "metric_param",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metric_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["metric_type_id"],
            ["metric_type.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("metric_param", schema=None) as batch_op:
        batch_op.create_index(
            "ix_metric_param_lookup", ["metric_type_id", "name", "effective_from"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("metric_param", schema=None) as batch_op:
        batch_op.drop_index("ix_metric_param_lookup")

    op.drop_table("metric_param")
    op.drop_table("metric_entry")
    with op.batch_alter_table("expense_item", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_expense_item_expense_id"))

    op.drop_table("expense_item")
    op.drop_table("metric_type")
    with op.batch_alter_table("expense", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_expense_occurred_on"))

    op.drop_table("expense")
    op.drop_table("setting")
    op.drop_table("category")
