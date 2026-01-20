"""initial migration

Revision ID: 7e3bc4973d6f
Revises: 
Create Date: 2025-09-03 16:43:12.842087

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geometry


# revision identifiers, used by Alembic.
revision: str = '7e3bc4973d6f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
    op.execute(text("CREATE EXTENSION IF NOT EXISTS adminpack WITH SCHEMA pg_catalog"))
    op.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
    op.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    op.create_table(
        "order_statuses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False, unique=True),
        schema="public",
    )
    op.create_table('sizes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('volume_ml',sa.Integer(),nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    schema='public'
    )
    op.create_table('product_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('firstname', sa.String(length=50), nullable=True),
    sa.Column('phone_number', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('tg_user_id', sa.BIGINT(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_bot', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tg_user_id'),
    schema='public'
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False, unique=True),
        schema="public",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger,
                  sa.ForeignKey("public.users.tg_user_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("finished_at", sa.DateTime, nullable=True, server_default=sa.func.now()),
        sa.Column("last_action", postgresql.JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("role_id", sa.Integer,
                  sa.ForeignKey("public.roles.id", ondelete="SET DEFAULT"),
                  nullable=False, server_default=sa.text("1")),
        schema="public",
    )
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.BIGINT(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('is_draft', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.ForeignKeyConstraint(['type_id'], ['public.product_types.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by'], ['public.users.tg_user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='public'
    )
    op.create_table(
        "product_sizes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer,
                  sa.ForeignKey("public.products.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("size_id", sa.Integer,
                  sa.ForeignKey("public.sizes.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("price", sa.Numeric(5, 1), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        schema="public",
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True),

        sa.Column("tg_user_id", sa.BigInteger,
                  sa.ForeignKey("public.users.tg_user_id", ondelete="CASCADE"),
                  nullable=False),

        sa.Column("manager_id", sa.BigInteger,
                  sa.ForeignKey("public.users.tg_user_id", ondelete="SET NULL"),
                  nullable=True),

        sa.Column("product_size_id", sa.Integer,
                  sa.ForeignKey("public.product_sizes.id", ondelete="CASCADE"),
                  nullable=False),

        sa.Column("status_id", sa.Integer,
                  sa.ForeignKey("public.order_statuses.id", ondelete="CASCADE"),
                  nullable=False),

        sa.Column("drink_count", sa.Integer, nullable=False),
        sa.Column("total_price", sa.Numeric(5, 1), nullable=False),

        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False,
                  server_default=sa.func.now()),

        sa.Column("customer_comment", sa.String(length=255), nullable=True),
        sa.Column("manager_comment", sa.String(length=255), nullable=True),

        sa.Column("is_active", sa.Boolean, nullable=False,
                  server_default=sa.text("true")),

        sa.Column("session_id", sa.Integer,
                  sa.ForeignKey("public.sessions.id", ondelete="RESTRICT"),
                  nullable=False),

        sa.Column("required_delivery", sa.Boolean, nullable=False,
                  server_default=sa.text("false")),

        sa.CheckConstraint("drink_count > 0", name="check_drink_count_positive"),
        sa.CheckConstraint("total_price >= 0", name="check_total_price_non_negative"),

        schema="public",
    )

    # 1. delivery_statuses
    op.create_table(
        "delivery_statuses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False, unique=True),
        schema="public",
    )

    # 2. delivery_zones
    op.create_table(
        "delivery_zones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("geometry", Geometry(geometry_type="POLYGON", srid=4326), nullable=False),
        sa.Column("cost", sa.Numeric(10, 2), nullable=False),
        schema="public",
    )

    # 3. delivery_intervals
    op.create_table(
        "delivery_intervals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False, unique=True),
        sa.Column("start_interval", sa.Time, nullable=False),
        sa.Column("end_interval", sa.Time, nullable=False),
        schema="public",
    )

    # 4. order_delivery
    op.create_table(
        "order_delivery",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("public.orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivery_address", sa.String(length=255), nullable=False),
        sa.Column("delivery_address_short", sa.String(length=100), nullable=True),
        sa.Column("delivery_point", Geometry(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("if_within", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("delivery_zone_id", sa.Integer, sa.ForeignKey("public.delivery_zones.id", ondelete="SET NULL"), nullable=True),
        sa.Column("delivery_date", sa.DateTime, nullable=False),
        sa.Column("delivery_interval_id", sa.Integer, sa.ForeignKey("public.delivery_intervals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delivery_cost", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("delivery_status_id", sa.Integer, sa.ForeignKey("public.delivery_statuses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        schema="public",
    )

    # GIST индекс для поиска по точкам
    op.create_index(
        "idx_order_delivery_point_gix",
        "order_delivery",
        ["delivery_point"],
        unique=False,
        postgresql_using="gist",
        schema="public",
    )



def downgrade() -> None:
    """Downgrade schema."""
    op.execute(text("DROP SCHEMA IF EXISTS public"))
    op.execute(text("DROP EXTENSION IF EXISTS adminpack WITH SCHEMA pg_catalog"))
    op.execute(text("DROP EXTENSION IF EXISTS pg_stat_statements"))
    op.execute(text("DROP EXTENSION IF EXISTS postgis"))

    op.drop_index("idx_order_delivery_point_gix", table_name="order_delivery", schema="public")

    op.drop_table('order_delivery', schema='public')
    op.drop_tables('delivery_intervals',schema='public')
    op.drop_tables('delivery_zones',schema='public')
    op.drop_tables('delivery_statuses',schema='public')  
    op.drop_table("orders", schema="public")
    op.drop_table("product_sizes", schema="public")      
    op.drop_table("products", schema="public")
    op.drop_table("users", schema="public")
    op.drop_table("sessions", schema="public")
    op.drop_table("roles", schema="public")
    op.drop_table("product_types", schema="public")
    op.drop_table("sizes", schema="public")
    op.drop_table("order_statuses", schema="public")
    

