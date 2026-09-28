"""shops: multitenancy (shops, locations, staff channels, shop_id everywhere)

- shops — тенант; shop_locations — точки (адрес + координаты); shop_channels — служебные чаты.
- shop_id у products, orders (+ location_id — точка выдачи), tasting_*, delivery_zones, users (менеджер).
- Всё существующее переносится в первый магазин «KrasPolHoney» с точкой на Плотинной, 4.
  Служебный чат и телефон магазина бот заполнит из ADMIN_CHAT_ID / SELLER_CONTACT при первом старте.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_SHOP_SLUG = "kraspolhoney"

# (таблица, ondelete) — у всего этого появляется обязательный shop_id = первый магазин
SHOP_SCOPED = [
    ("products", "RESTRICT"),
    ("tasting_events", "CASCADE"),
    ("tasting_signups", "CASCADE"),
    ("delivery_zones", "CASCADE"),
]


def _add_shop_id(table: str, ondelete: str, fill_sql: str) -> None:
    op.add_column(table, sa.Column("shop_id", sa.Integer(), nullable=True), schema="public")
    op.execute(fill_sql)
    op.alter_column(table, "shop_id", nullable=False, schema="public")
    op.create_foreign_key(
        f"{table}_shop_id_fkey", table, "shops", ["shop_id"], ["id"],
        source_schema="public", referent_schema="public", ondelete=ondelete,
    )
    op.create_index(f"ix_{table}_shop_id", table, ["shop_id"], schema="public")


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="public",
    )
    op.create_table(
        "shop_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("point", Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True),
        sa.Column("is_pickup", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("opening_hours", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["shop_id"], ["public.shops.id"], ondelete="CASCADE"),
        schema="public",
    )
    op.create_index("ix_shop_locations_shop_id", "shop_locations", ["shop_id"], schema="public")
    op.create_table(
        "shop_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("address", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False, server_default=sa.text("'staff'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["shop_id"], ["public.shops.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("shop_id", "provider", "purpose", name="uq_shop_channels_shop_provider_purpose"),
        schema="public",
    )

    # первый магазин и его точка — то, что раньше было захардкожено в utils/constants.py
    shop_id = op.get_bind().execute(sa.text(
        "INSERT INTO public.shops (slug, name) VALUES (:slug, 'KrasPolHoney') RETURNING id"
    ), {"slug": DEFAULT_SHOP_SLUG}).scalar_one()
    location_id = op.get_bind().execute(sa.text(
        "INSERT INTO public.shop_locations (shop_id, name, address, point) VALUES "
        "(:shop, 'Пасека', 'Красная Поляна, ул. Плотинная, д. 4', "
        " ST_SetSRID(ST_MakePoint(40.200094, 43.672805), 4326)) RETURNING id"
    ), {"shop": shop_id}).scalar_one()

    for table, ondelete in SHOP_SCOPED:
        _add_shop_id(table, ondelete, f"UPDATE public.{table} SET shop_id = {shop_id}")
    # зоны доставки уникальны внутри магазина, а не глобально
    op.execute("ALTER TABLE public.delivery_zones DROP CONSTRAINT IF EXISTS delivery_zones_name_key")
    op.create_unique_constraint("uq_delivery_zones_shop_name", "delivery_zones", ["shop_id", "name"], schema="public")

    # заказ — в магазине своего товара
    _add_shop_id(
        "orders", "RESTRICT",
        "UPDATE public.orders o SET shop_id = p.shop_id FROM public.product_sizes ps "
        "JOIN public.products p ON p.id = ps.product_id WHERE ps.id = o.product_size_id",
    )
    op.add_column("orders", sa.Column("location_id", sa.Integer(), nullable=True), schema="public")
    op.create_foreign_key(
        "orders_location_id_fkey", "orders", "shop_locations", ["location_id"], ["id"],
        source_schema="public", referent_schema="public", ondelete="SET NULL",
    )
    op.execute(f"UPDATE public.orders SET location_id = {location_id}")

    # менеджер работает в одном магазине
    op.add_column("users", sa.Column("shop_id", sa.Integer(), nullable=True), schema="public")
    op.create_foreign_key(
        "users_shop_id_fkey", "users", "shops", ["shop_id"], ["id"],
        source_schema="public", referent_schema="public", ondelete="SET NULL",
    )
    op.execute(f"UPDATE public.users SET shop_id = {shop_id} WHERE role_id = 4")


def downgrade() -> None:
    op.drop_constraint("users_shop_id_fkey", "users", schema="public", type_="foreignkey")
    op.drop_column("users", "shop_id", schema="public")

    op.drop_constraint("orders_location_id_fkey", "orders", schema="public", type_="foreignkey")
    op.drop_column("orders", "location_id", schema="public")

    op.drop_constraint("uq_delivery_zones_shop_name", "delivery_zones", schema="public", type_="unique")
    op.create_unique_constraint("delivery_zones_name_key", "delivery_zones", ["name"], schema="public")
    for table, _ in [*SHOP_SCOPED, ("orders", "RESTRICT")]:
        op.drop_index(f"ix_{table}_shop_id", table_name=table, schema="public")
        op.drop_constraint(f"{table}_shop_id_fkey", table, schema="public", type_="foreignkey")
        op.drop_column(table, "shop_id", schema="public")

    op.drop_table("shop_channels", schema="public")
    op.drop_index("ix_shop_locations_shop_id", table_name="shop_locations", schema="public")
    op.drop_table("shop_locations", schema="public")
    op.drop_table("shops", schema="public")
