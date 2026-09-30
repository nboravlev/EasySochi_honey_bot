"""admin panel: one-time login links and browser sessions

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-10-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _common() -> list:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "admin_login_tokens", *_common(),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_index("ix_admin_login_tokens_user_id", "admin_login_tokens", ["user_id"], schema="public")
    op.create_table(
        "admin_sessions", *_common(),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        schema="public",
    )
    op.create_index("ix_admin_sessions_user_id", "admin_sessions", ["user_id"], schema="public")


def downgrade() -> None:
    op.drop_table("admin_sessions", schema="public")
    op.drop_table("admin_login_tokens", schema="public")
