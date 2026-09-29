"""inbound_message: stored reply, sent marker, and edits share the message id

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inbound_message", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reply", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("replied_at", sa.String(length=32), nullable=True))
        batch_op.drop_constraint("uq_inbound_chat_message", type_="unique")
        batch_op.create_index("ix_inbound_chat_message", ["tg_chat_id", "tg_message_id"])


def downgrade() -> None:
    with op.batch_alter_table("inbound_message", schema=None) as batch_op:
        batch_op.drop_index("ix_inbound_chat_message")
        batch_op.create_unique_constraint(
            "uq_inbound_chat_message", ["tg_chat_id", "tg_message_id"]
        )
        batch_op.drop_column("replied_at")
        batch_op.drop_column("reply")
