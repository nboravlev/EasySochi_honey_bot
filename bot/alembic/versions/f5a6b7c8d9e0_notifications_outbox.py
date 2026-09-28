"""notifications outbox: durable outgoing messages with retries

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("address", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("public.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shop_id", sa.Integer(), sa.ForeignKey("public.shops.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("external_message_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name="check_notification_status"),
        schema="public",
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"], schema="public")
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], schema="public")
    op.create_index(
        "ix_notifications_due", "notifications", ["provider", "next_attempt_at"],
        schema="public", postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("notifications", schema="public")
