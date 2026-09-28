"""Сквозные тесты на временной PostgreSQL (RUN_DB_TESTS=1, после alembic upgrade head).

⚠️ Перед каждым тестом пользовательские таблицы очищаются (TRUNCATE) — только тестовая база!
"""
import os
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from telegram.ext import PicklePersistence

from config import get_db_settings
from db.models import Product, ProductSize, ProductType, Shop, ShopLocation, Size, User
from domain.enums import Provider, Role
from services import identity, shops

from .harness import Bot, FakeTelegram, Person

if os.getenv("RUN_DB_TESTS") != "1":
    pytest.skip("нужна PostgreSQL: RUN_DB_TESTS=1", allow_module_level=True)

ADMIN_CHAT_ID = -100500   # tests/conftest.py
OWNER = Person(42, "Владелец", "owner_test")
MANAGER = Person(111, "Мария", "manager_test")
ADMIN_CHAT_MEMBER = Person(3001, "Помощник")     # участник админ-чата, не менеджер
BUYER = Person(5001, "Анна", "anna_test")
STRANGER = Person(6001, "Посторонний")

# справочники (статусы, роли, размеры, тара) и магазин-витрину не трогаем — их создаёт миграция
USER_TABLES = (
    "tasting_signups, tasting_events, order_packages, order_delivery, orders, sessions, "
    "productsize_images, images, product_sizes, products, product_types, user_identities, users, sources, "
    "shop_channels, notifications"
)
STOREFRONT = "kraspolhoney"
SHOP_B = "test-shop-b"
STAFF_CHAT_B = -200600



@dataclass
class Catalog:
    type_id: int
    product_size_id: int
    shop_id: int


async def _reset_and_seed() -> Catalog:
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {USER_TABLES} RESTART IDENTITY CASCADE"))
            await conn.execute(text("DELETE FROM shops WHERE slug <> :slug"), {"slug": STOREFRONT})
        async with AsyncSession(engine, expire_on_commit=False) as session:
            shop = await session.scalar(select(Shop).where(Shop.slug == STOREFRONT))
            await shops.set_staff_channel(session, shop.id, Provider.TELEGRAM, ADMIN_CHAT_ID)
            manager = await _person(session, MANAGER)
            manager.role_id, manager.shop_id = Role.MANAGER, shop.id
            product_type = ProductType(name="Цветочный")
            session.add(product_type)
            await session.flush()
            size = await session.scalar(select(Size).where(Size.name == Decimal("1.0")))
            product = Product(name="Горный мёд", description="Тестовый", type_id=product_type.id, shop_id=shop.id,
                              created_by=manager.id, is_active=True, is_draft=False)
            session.add(product)
            await session.flush()
            product_size = ProductSize(product_id=product.id, size_id=size.id, price=Decimal("1500"), is_active=True)
            session.add(product_size)
            await session.commit()
            return Catalog(type_id=product_type.id, product_size_id=product_size.id, shop_id=shop.id)
    finally:
        await engine.dispose()


async def _person(session, person: Person) -> User:
    user, _ = await identity.get_or_create_user(session, Provider.TELEGRAM, person.id, username=person.username)
    user.firstname, user.username = person.first_name, person.username
    await session.flush()
    return user


async def register(person: Person) -> None:
    """Пользователь, уже прошедший регистрацию."""
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with AsyncSession(engine) as session:
        await _person(session, person)
        await session.commit()
    await engine.dispose()


async def create_second_shop(manager: Person) -> int:
    """Магазин Б со своим служебным чатом, менеджером и товаром."""
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        shop = Shop(slug=SHOP_B, name="Магазин Б")
        session.add(shop)
        await session.flush()
        session.add(ShopLocation(shop_id=shop.id, name="Склад Б", address="Адлер, ул. Тестовая, 1"))
        await shops.set_staff_channel(session, shop.id, Provider.TELEGRAM, STAFF_CHAT_B)
        user = await _person(session, manager)
        user.role_id, user.shop_id = Role.MANAGER, shop.id
        await session.commit()
        shop_id = shop.id
    await engine.dispose()
    return shop_id


async def user_value(column: str, person: Person):
    """Значение колонки users для человека по его Telegram ID."""
    rows = await query(
        f"SELECT u.{column} FROM users u JOIN user_identities i ON i.user_id = u.id "
        "WHERE i.provider = 'telegram' AND i.external_id = :tg",
        tg=str(person.id),
    )
    return rows[0][0] if rows else None


async def query(sql: str, **params):
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        result = (await conn.execute(text(sql), params)).all()
    await engine.dispose()
    return result


async def execute(sql: str, **params) -> None:
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)
    await engine.dispose()


async def start_bot(state_file) -> Bot:
    from main import build_application  # импорт после настройки окружения в tests/conftest.py

    _reset_caches()
    telegram = FakeTelegram()
    app = build_application(persistence=PicklePersistence(filepath=state_file), request=telegram)
    harness = Bot(app, telegram)

    async def capture_error(update, context):
        harness.errors.append(context.error)
    app.add_error_handler(capture_error)
    await app.initialize()
    return harness


def _reset_caches() -> None:
    """Кэши «Telegram ID → users.id» и профилей живут в процессе, а тесты очищают таблицы
    с RESTART IDENTITY: без сброса следующий тест получил бы чужие users.id."""
    from services.users import invalidate_profile_cache
    from utils.access import forget_users

    forget_users()
    invalidate_profile_cache()


async def stop_bot(harness: Bot) -> None:
    from db import db_async

    if harness.stopped:
        return
    harness.stopped = True
    await harness.app.shutdown()          # сбрасывает состояние в файл persistence
    await db_async.engine.dispose()       # пул соединений привязан к event loop теста
    _reset_caches()


@pytest.fixture
async def catalog() -> Catalog:
    return await _reset_and_seed()


@pytest.fixture
async def bot(catalog, tmp_path):
    harness = await start_bot(tmp_path / "state.pickle")
    try:
        yield harness
    finally:
        await stop_bot(harness)
