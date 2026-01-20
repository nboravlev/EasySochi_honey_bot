"""create sources table

Revision ID: 20250927_create_sources
Revises: <предыдущая_миграция>
Create Date: 2025-09-27
"""
from alembic import op
import sqlalchemy as sa
from typing import Sequence, Union
from datetime import datetime


# revision identifiers, used by Alembic.
revision: str = '7e3bc4973d6d'
down_revision: Union[str, Sequence[str], None] = '7e3bc4973d6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger, nullable=True, unique=True),
        sa.Column("suffix", sa.String(length=50), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        schema="public",
    )


def downgrade():
    op.drop_table("sources", schema="public")
