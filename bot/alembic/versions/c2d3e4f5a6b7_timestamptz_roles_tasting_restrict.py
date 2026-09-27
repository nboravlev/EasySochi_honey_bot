"""timestamptz, users.role_id, tasting tables, RESTRICT for orders

- Все timestamp without time zone в public → timestamptz. Старые значения писались
  через datetime.utcnow(), поэтому трактуются как UTC.
- orders: tg_user_id / product_size_id / status_id — ON DELETE RESTRICT вместо CASCADE
  (удаление пользователя, размера или статуса больше не стирает историю заказов).
- users.role_id (FK roles, по умолчанию 1 — пользователь). Менеджеров назначает владелец в боте;
  при первом запуске бот переносит в БД MANAGER_LIST из .env.
- tasting_events / tasting_signups. Лист ожидания переносится из sessions (role_id=3, sent_message=false).
- Индексы для частых выборок заказов.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SKIP_TABLES = ("alembic_version", "spatial_ref_sys")

ORDER_FKS = [
    # (constraint, column, referred table, referred column, old ondelete)
    ("orders_tg_user_id_fkey", "tg_user_id", "users", "tg_user_id", "CASCADE"),
    ("orders_product_size_id_fkey", "product_size_id", "product_sizes", "id", "CASCADE"),
    ("orders_status_id_fkey", "status_id", "order_statuses", "id", "CASCADE"),
]


def _timestamp_columns(data_type: str) -> list[tuple[str, str]]:
    # только обычные таблицы: расширения (pg_stat_statements и др.) создают в public представления,
    # у которых тип колонки менять нельзя
    rows = op.get_bind().execute(
        sa.text(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
            "AND c.data_type = :data_type AND c.table_name NOT IN :skip "
            "ORDER BY c.table_name, c.column_name"
        ).bindparams(sa.bindparam("skip", expanding=True)),
        {"data_type": data_type, "skip": list(SKIP_TABLES)},
    )
    return [(r.table_name, r.column_name) for r in rows]


def _set_order_fks(ondelete_for) -> None:
    for name, column, ref_table, ref_column, old in ORDER_FKS:
        op.execute(f"ALTER TABLE public.orders DROP CONSTRAINT IF EXISTS {name}")
        op.create_foreign_key(
            name, "orders", ref_table, [column], [ref_column],
            source_schema="public", referent_schema="public", ondelete=ondelete_for(old),
        )


def upgrade() -> None:
    # 1. timestamptz
    for table, column in _timestamp_columns("timestamp without time zone"):
        op.execute(
            f'ALTER TABLE public."{table}" ALTER COLUMN "{column}" '
            f'TYPE timestamptz USING "{column}" AT TIME ZONE \'UTC\''
        )

    # 2. история заказов не удаляется каскадом
    _set_order_fks(lambda old: "RESTRICT")

    # 3. роль пользователя
    op.add_column(
        "users",
        sa.Column("role_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="public",
    )
    op.create_foreign_key(
        "users_role_id_fkey", "users", "roles", ["role_id"], ["id"],
        source_schema="public", referent_schema="public", ondelete="RESTRICT",
    )

    # 4. дегустации
    op.create_table(
        "tasting_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["public.users.tg_user_id"], ondelete="SET NULL"),
        schema="public",
    )
    op.create_table(
        "tasting_signups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'waiting'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tg_user_id"], ["public.users.tg_user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["public.tasting_events.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('waiting', 'invited', 'going', 'declined')", name="check_tasting_signup_status"
        ),
        schema="public",
    )
    op.create_index(
        "uq_tasting_signups_waiting_user", "tasting_signups", ["tg_user_id"],
        unique=True, schema="public", postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_index("ix_tasting_signups_event_status", "tasting_signups", ["event_id", "status"], schema="public")

    # лист ожидания из старых сессий «записался на дегустацию»
    op.execute(
        "INSERT INTO public.tasting_signups (tg_user_id, status, created_at, updated_at) "
        "SELECT DISTINCT ON (tg_user_id) tg_user_id, 'waiting', created_at, created_at "
        "FROM public.sessions WHERE role_id = 3 AND sent_message = false "
        "ORDER BY tg_user_id, created_at"
    )

    # 5. индексы под списки заказов и статистику
    op.create_index("ix_orders_status_id", "orders", ["status_id"], schema="public")
    op.create_index("ix_orders_tg_user_id", "orders", ["tg_user_id"], schema="public")


def downgrade() -> None:
    op.drop_index("ix_orders_tg_user_id", table_name="orders", schema="public")
    op.drop_index("ix_orders_status_id", table_name="orders", schema="public")

    op.drop_index("ix_tasting_signups_event_status", table_name="tasting_signups", schema="public")
    op.drop_index("uq_tasting_signups_waiting_user", table_name="tasting_signups", schema="public")
    op.drop_table("tasting_signups", schema="public")
    op.drop_table("tasting_events", schema="public")

    op.drop_constraint("users_role_id_fkey", "users", schema="public", type_="foreignkey")
    op.drop_column("users", "role_id", schema="public")

    _set_order_fks(lambda old: old)

    for table, column in _timestamp_columns("timestamp with time zone"):
        op.execute(
            f'ALTER TABLE public."{table}" ALTER COLUMN "{column}" '
            f'TYPE timestamp USING "{column}" AT TIME ZONE \'UTC\''
        )
