"""user identities: platform-neutral users, all references via users.id

- user_identities (provider, external_id → user_id). Telegram ID переезжает сюда из users.tg_user_id.
- Все ссылки на пользователя — через users.id вместо Telegram ID:
  orders.tg_user_id → orders.customer_id; orders.manager_id; products.created_by / updated_by;
  sessions.tg_user_id → sessions.user_id; tasting_events.created_by; tasting_signups.tg_user_id → user_id.
- users.tg_user_id удаляется.

Откат возможен, пока у всех пользователей есть Telegram-аккаунт (пока не появились пользователи VK/сайта).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (таблица, колонка с Telegram ID, новая колонка с users.id, новая обязательна, ondelete новой,
#  ondelete старой — None, если внешнего ключа не было, старая была обязательной)
REFERENCES = [
    ("orders", "tg_user_id", "customer_id", True, "RESTRICT", "RESTRICT", True),
    ("orders", "manager_id", "manager_id", False, "SET NULL", "SET NULL", False),
    # автор карточки может уйти — карточка остаётся у магазина
    ("products", "created_by", "created_by", False, "SET NULL", "CASCADE", True),
    ("products", "updated_by", "updated_by", False, "SET NULL", None, False),
    ("sessions", "tg_user_id", "user_id", True, "CASCADE", "CASCADE", True),
    ("tasting_events", "created_by", "created_by", False, "SET NULL", "SET NULL", False),
    ("tasting_signups", "tg_user_id", "user_id", True, "CASCADE", "CASCADE", True),
]


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "external_id", name="uq_user_identities_provider_external"),
        schema="public",
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"], schema="public")
    op.execute(
        "INSERT INTO public.user_identities (user_id, provider, external_id, username, created_at) "
        "SELECT id, 'telegram', tg_user_id::text, username, COALESCE(created_at, now()) FROM public.users"
    )

    for table, old, new, required, ondelete, _, _ in REFERENCES:
        tmp = f"{new}__new"
        op.add_column(table, sa.Column(tmp, sa.Integer(), nullable=True), schema="public")
        op.execute(
            f"UPDATE public.{table} t SET {tmp} = u.id FROM public.users u WHERE u.tg_user_id = t.{old}"
        )
        # старая колонка уходит вместе со своим внешним ключом и индексами
        op.drop_column(table, old, schema="public")
        op.alter_column(table, tmp, new_column_name=new, schema="public")
        if required:
            op.alter_column(table, new, nullable=False, schema="public")
        op.create_foreign_key(
            f"{table}_{new}_fkey", table, "users", [new], ["id"],
            source_schema="public", referent_schema="public", ondelete=ondelete,
        )

    op.create_index("ix_orders_customer_id", "orders", ["customer_id"], schema="public")
    op.create_index(
        "uq_tasting_signups_waiting_user", "tasting_signups", ["shop_id", "user_id"],
        unique=True, schema="public", postgresql_where=sa.text("status = 'waiting'"),
    )
    op.drop_column("users", "tg_user_id", schema="public")


def downgrade() -> None:
    op.add_column("users", sa.Column("tg_user_id", sa.BigInteger(), nullable=True), schema="public")
    op.execute(
        "UPDATE public.users u SET tg_user_id = i.external_id::bigint FROM public.user_identities i "
        "WHERE i.user_id = u.id AND i.provider = 'telegram'"
    )
    missing = op.get_bind().execute(sa.text("SELECT count(*) FROM public.users WHERE tg_user_id IS NULL")).scalar()
    if missing:
        raise RuntimeError(f"Откат невозможен: у {missing} пользователей нет Telegram-аккаунта")
    op.alter_column("users", "tg_user_id", nullable=False, schema="public")
    op.create_unique_constraint("users_tg_user_id_key", "users", ["tg_user_id"], schema="public")

    op.drop_index("uq_tasting_signups_waiting_user", table_name="tasting_signups", schema="public")
    op.drop_index("ix_orders_customer_id", table_name="orders", schema="public")

    for table, old, new, _, _, old_ondelete, old_required in reversed(REFERENCES):
        tmp = f"{old}__old"
        op.add_column(table, sa.Column(tmp, sa.BigInteger(), nullable=True), schema="public")
        op.execute(f"UPDATE public.{table} t SET {tmp} = u.tg_user_id FROM public.users u WHERE u.id = t.{new}")
        op.drop_column(table, new, schema="public")
        op.alter_column(table, tmp, new_column_name=old, schema="public")
        if old_required:
            op.alter_column(table, old, nullable=False, schema="public")
        if old_ondelete:
            op.create_foreign_key(
                f"{table}_{old}_fkey", table, "users", [old], ["tg_user_id"],
                source_schema="public", referent_schema="public", ondelete=old_ondelete,
            )

    op.create_index("ix_orders_tg_user_id", "orders", ["tg_user_id"], schema="public")
    op.create_index(
        "uq_tasting_signups_waiting_user", "tasting_signups", ["tg_user_id"],
        unique=True, schema="public", postgresql_where=sa.text("status = 'waiting'"),
    )
    op.drop_index("ix_user_identities_user_id", table_name="user_identities", schema="public")
    op.drop_table("user_identities", schema="public")
