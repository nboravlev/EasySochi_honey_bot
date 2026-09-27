"""Интеграционные тесты сервисов на реальной PostgreSQL со схемой после `alembic upgrade head`.

Запуск: RUN_DB_TESTS=1 и переменные POSTGRES_*/DB_HOST (в CI — job migrations).
Каждый тест идёт в транзакции, которая откатывается: база остаётся чистой.
"""
import os
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from config import get_db_settings
from db.models import Product, ProductSize, ProductType, Size, User

if os.getenv("RUN_DB_TESTS") != "1":
    pytest.skip("нужна PostgreSQL: RUN_DB_TESTS=1", allow_module_level=True)

BUYER_ID = 900001
SELLER_ID = 900002
OTHER_SELLER_ID = 900003


@pytest.fixture
async def session():
    # свой движок без пула: у каждого теста свой event loop
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        db = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            await db.close()
            await trans.rollback()
    await engine.dispose()


@pytest.fixture
async def catalog(session):
    """Покупатель, два продавца, по товару у каждого (1 кг по 1500 ₽ и 0,5 кг по 800 ₽)."""
    session.add_all([
        User(tg_user_id=BUYER_ID, firstname="Покупатель", username="buyer_test", is_bot=False),
        User(tg_user_id=SELLER_ID, firstname="Продавец", username="seller_test", is_bot=False),
        User(tg_user_id=OTHER_SELLER_ID, firstname="Другой", is_bot=False),
    ])
    product_type = ProductType(name="Тестовый сорт")
    session.add(product_type)
    await session.flush()

    sizes = {float(s.name): s for s in (await session.scalars(select(Size))).all()}
    result = {}
    for key, seller, size, price in (
        ("own", SELLER_ID, sizes[1.0], "1500.00"),
        ("other", OTHER_SELLER_ID, sizes[0.5], "800.00"),
    ):
        product = Product(name=f"Мёд {key}", type_id=product_type.id, created_by=seller,
                          is_active=True, is_draft=False)
        session.add(product)
        await session.flush()
        product_size = ProductSize(product_id=product.id, size_id=size.id, price=Decimal(price), is_active=True)
        session.add(product_size)
        await session.flush()
        result[key] = product_size
    return result
