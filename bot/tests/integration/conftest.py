"""Интеграционные тесты сервисов на реальной PostgreSQL со схемой после `alembic upgrade head`.

Запуск: RUN_DB_TESTS=1 и переменные POSTGRES_*/DB_HOST (в CI — job migrations).
Каждый тест идёт в транзакции, которая откатывается: база остаётся чистой.
"""
import os
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from config import get_db_settings
from db.models import Product, ProductSize, ProductType, Shop, ShopLocation, Size, User
from domain.enums import Provider
from services import identity

if os.getenv("RUN_DB_TESTS") != "1":
    pytest.skip("нужна PostgreSQL: RUN_DB_TESTS=1", allow_module_level=True)

# Telegram ID участников
BUYER_TG = 900001
SELLER_TG = 900002
OTHER_SELLER_TG = 900003


@dataclass
class World:
    buyer: User
    seller: User            # менеджер магазина A
    other_seller: User      # менеджер магазина B
    shop_a: Shop
    shop_b: Shop
    location_a: ShopLocation
    own: ProductSize        # товар магазина A: 1 кг по 1500 ₽
    other: ProductSize      # товар магазина B: 0,5 кг по 800 ₽
    type_id: int


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


async def make_user(session, tg_id: int, firstname: str, username: str | None = None) -> User:
    user, _ = await identity.get_or_create_user(session, Provider.TELEGRAM, tg_id, username=username)
    user.firstname = firstname
    user.username = username
    await session.flush()
    return user


@pytest.fixture
async def world(session) -> World:
    # свои магазины, не пасека из миграции: данные других тестов не влияют на статистику
    shop_a = Shop(slug="test-shop-a", name="Магазин А")
    shop_b = Shop(slug="test-shop-b", name="Магазин Б")
    session.add_all([shop_a, shop_b])
    await session.flush()
    location_a = ShopLocation(shop_id=shop_a.id, name="Пасека А", address="Красная Поляна, ул. Плотинная, д. 4",
                              point="SRID=4326;POINT(40.200094 43.672805)")
    session.add(location_a)
    session.add(ShopLocation(shop_id=shop_b.id, name="Склад Б", address="Адлер, ул. Тестовая, 1"))

    buyer = await make_user(session, BUYER_TG, "Покупатель", "buyer_test")
    seller = await make_user(session, SELLER_TG, "Продавец", "seller_test")
    other_seller = await make_user(session, OTHER_SELLER_TG, "Другой")

    product_type = ProductType(name="Тестовый сорт")
    session.add(product_type)
    await session.flush()
    sizes = {float(s.name): s for s in (await session.scalars(select(Size))).all()}
    offers = {}
    for key, shop, author, size, price in (
        ("own", shop_a, seller, sizes[1.0], "1500.00"),
        ("other", shop_b, other_seller, sizes[0.5], "800.00"),
    ):
        product = Product(name=f"Мёд {key}", type_id=product_type.id, shop_id=shop.id, created_by=author.id,
                          is_active=True, is_draft=False)
        session.add(product)
        await session.flush()
        offer = ProductSize(product_id=product.id, size_id=size.id, price=Decimal(price), is_active=True)
        session.add(offer)
        await session.flush()
        offers[key] = offer
    return World(buyer=buyer, seller=seller, other_seller=other_seller, shop_a=shop_a, shop_b=shop_b,
                 location_a=location_a, own=offers["own"], other=offers["other"], type_id=product_type.id)
