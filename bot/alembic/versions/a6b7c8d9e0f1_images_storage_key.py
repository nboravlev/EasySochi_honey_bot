"""images: own storage key, Telegram file_id becomes a cache

Существующие фото остаются с tg_file_id; бот при старте скачивает их в хранилище
(utils.telegram_media.backfill_media_job) и заполняет storage_key.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("images", sa.Column("storage_key", sa.String(255), nullable=True), schema="public")
    op.alter_column("images", "tg_file_id", existing_type=sa.String(), nullable=True, schema="public")
    op.create_check_constraint(
        "check_images_has_source", "images", "storage_key IS NOT NULL OR tg_file_id IS NOT NULL", schema="public"
    )


def downgrade() -> None:
    bind = op.get_bind()
    missing = bind.execute(sa.text("SELECT count(*) FROM public.images WHERE tg_file_id IS NULL")).scalar()
    if missing:
        raise RuntimeError(
            f"{missing} фото есть только в хранилище (без tg_file_id) — откат потерял бы их. "
            "Сначала отправьте их в Telegram или удалите строки images."
        )
    op.drop_constraint("check_images_has_source", "images", schema="public")
    op.alter_column("images", "tg_file_id", existing_type=sa.String(), nullable=False, schema="public")
    op.drop_column("images", "storage_key", schema="public")
