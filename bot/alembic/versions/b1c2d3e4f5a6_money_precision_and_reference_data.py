"""money precision, product_count check, reference data

- Цены и суммы: NUMERIC(5,1)/NUMERIC(4,1) → NUMERIC(10,2).
  Прежний тип вмещал максимум 9 999,9 ₽ за заказ.
- CHECK product_count > 0 (NOT VALID — существующие строки не проверяются).
- Справочники, на ID которых опирается код (utils/constants.py):
  order_statuses 1–8 и roles 1–4. Вставка ON CONFLICT DO NOTHING — на
  рабочей базе уже заполненные строки не меняются.
- Тара и размеры 0.5/1.0/1.5 кг — только если таблицы пустые (свежая установка).

Revision ID: b1c2d3e4f5a6
Revises: fb1f7efcb9e0
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'fb1f7efcb9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MONEY_COLUMNS = [
    # (table, column, old_type)
    ("orders", "total_price", sa.Numeric(5, 1)),
    ("product_sizes", "price", sa.Numeric(5, 1)),
    ("packages", "price", sa.Numeric(4, 1)),
]

ORDER_STATUSES = [
    (1, "Создан"),
    (2, "Покупатель сообщил дату"),
    (3, "В работе"),
    (4, "Готов к выдаче"),
    (5, "Выдан"),
    (6, "Отклонён"),
    (7, "Просрочен"),
    (8, "Черновик"),
]

ROLES = [
    (1, "user"),
    (2, "buyer"),
    (3, "tasting"),
    (4, "manager"),
]


def _seed_by_id(table: str, rows: list[tuple[int, str]]) -> None:
    for row_id, name in rows:
        op.execute(
            sa.text(
                f"INSERT INTO public.{table} (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"
            ).bindparams(id=row_id, name=name)
        )
    # явные id не двигают sequence — выравниваем, чтобы следующие вставки не упёрлись в PK
    op.execute(
        f"SELECT setval(pg_get_serial_sequence('public.{table}', 'id'), "
        f"(SELECT COALESCE(MAX(id), 1) FROM public.{table}))"
    )


def upgrade() -> None:
    for table, column, old_type in MONEY_COLUMNS:
        op.alter_column(
            table, column,
            existing_type=old_type,
            type_=sa.Numeric(10, 2),
            existing_nullable=False,
            schema="public",
        )

    op.execute(
        "ALTER TABLE public.orders "
        "ADD CONSTRAINT check_product_count_positive CHECK (product_count > 0) NOT VALID"
    )

    _seed_by_id("order_statuses", ORDER_STATUSES)
    _seed_by_id("roles", ROLES)

    # Каталог тары и размеров — только для пустой базы, рабочие данные не трогаем
    op.execute(
        "INSERT INTO public.packages (name, price) "
        "SELECT 'Стеклянная банка', 0 "
        "WHERE NOT EXISTS (SELECT 1 FROM public.packages)"
    )
    op.execute(
        "INSERT INTO public.sizes (name, volume_ml, package_id) "
        "SELECT v.name, NULL, (SELECT MIN(id) FROM public.packages) "
        "FROM (VALUES (0.5), (1.0), (1.5)) AS v(name) "
        "WHERE NOT EXISTS (SELECT 1 FROM public.sizes)"
    )


def downgrade() -> None:
    # справочники не удаляем: на них ссылаются заказы и сессии
    op.execute("ALTER TABLE public.orders DROP CONSTRAINT IF EXISTS check_product_count_positive")
    for table, column, old_type in MONEY_COLUMNS:
        op.alter_column(
            table, column,
            existing_type=sa.Numeric(10, 2),
            type_=old_type,
            existing_nullable=False,
            schema="public",
        )
