"""inbound_message table and the telegram expense source

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tg_update_id", sa.Integer(), nullable=False),
        sa.Column("tg_chat_id", sa.Integer(), nullable=False),
        sa.Column("tg_message_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("parsed", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "status IN ('saved', 'question', 'command', 'rejected', 'unauthorized', 'error')",
            name="ck_inbound_status",
        ),
        sa.ForeignKeyConstraint(["expense_id"], ["expense.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tg_update_id"),
        sa.UniqueConstraint("tg_chat_id", "tg_message_id", name="uq_inbound_chat_message"),
    )
    with op.batch_alter_table("expense", schema=None) as batch_op:
        batch_op.drop_constraint("ck_expense_source", type_="check")
        batch_op.create_check_constraint(
            "ck_expense_source", "source IN ('web', 'metric', 'telegram')"
        )


def downgrade() -> None:
    with op.batch_alter_table("expense", schema=None) as batch_op:
        batch_op.drop_constraint("ck_expense_source", type_="check")
        batch_op.create_check_constraint("ck_expense_source", "source IN ('web', 'metric')")
    op.drop_table("inbound_message")
