"""income: extra income that raises the monthly target of its month

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "income",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.String(length=32), nullable=True),
        sa.CheckConstraint("amount_minor > 0", name="ck_income_amount_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("income", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_income_received_on"), ["received_on"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("income", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_income_received_on"))
    op.drop_table("income")
