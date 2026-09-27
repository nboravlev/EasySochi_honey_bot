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
from db.models import Product, ProductSize, ProductType, Size, User
from domain.enums import Role

from .harness import Bot, FakeTelegram, Person

if os.getenv("RUN_DB_TESTS") != "1":
    pytest.skip("нужна PostgreSQL: RUN_DB_TESTS=1", allow_module_level=True)

ADMIN_CHAT_ID = -100500   # tests/conftest.py
OWNER = Person(42, "Владелец", "owner_test")
MANAGER = Person(111, "Мария", "manager_test")
ADMIN_CHAT_MEMBER = Person(3001, "Помощник")     # участник админ-чата, не менеджер
BUYER = Person(5001, "Анна", "anna_test")
STRANGER = Person(6001, "Посторонний")

# справочники (статусы, роли, размеры, тара) не трогаем — их создаёт миграция
USER_TABLES = (
    "tasting_signups, tasting_events, order_packages, order_delivery, orders, sessions, "
    "productsize_images, images, product_sizes, products, product_types, users, sources"
)


@dataclass
class Catalog:
    type_id: int
    product_size_id: int


async def _reset_and_seed() -> Catalog:
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {USER_TABLES} RESTART IDENTITY CASCADE"))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(User(tg_user_id=MANAGER.id, firstname=MANAGER.first_name, username=MANAGER.username,
                             is_bot=False, role_id=Role.MANAGER))
            product_type = ProductType(name="Цветочный")
            session.add(product_type)
            await session.flush()
            size = await session.scalar(select(Size).where(Size.name == Decimal("1.0")))
            product = Product(name="Горный мёд", description="Тестовый", type_id=product_type.id,
                              created_by=MANAGER.id, is_active=True, is_draft=False)
            session.add(product)
            await session.flush()
            product_size = ProductSize(product_id=product.id, size_id=size.id, price=Decimal("1500"), is_active=True)
            session.add(product_size)
            await session.commit()
            return Catalog(type_id=product_type.id, product_size_id=product_size.id)
    finally:
        await engine.dispose()


async def register(person: Person) -> None:
    """Пользователь, уже прошедший регистрацию."""
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with AsyncSession(engine) as session:
        session.add(User(tg_user_id=person.id, firstname=person.first_name, username=person.username, is_bot=False))
        await session.commit()
    await engine.dispose()


async def query(sql: str, **params):
    engine = create_async_engine(get_db_settings().database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        result = (await conn.execute(text(sql), params)).all()
    await engine.dispose()
    return result


async def start_bot(state_file) -> Bot:
    from main import build_application  # импорт после настройки окружения в tests/conftest.py

    telegram = FakeTelegram()
    app = build_application(persistence=PicklePersistence(filepath=state_file), request=telegram)
    harness = Bot(app, telegram)

    async def capture_error(update, context):
        harness.errors.append(context.error)
    app.add_error_handler(capture_error)
    await app.initialize()
    return harness


async def stop_bot(harness: Bot) -> None:
    from db import db_async
    from services.users import invalidate_role_cache

    if harness.stopped:
        return
    harness.stopped = True
    await harness.app.shutdown()          # сбрасывает состояние в файл persistence
    await db_async.engine.dispose()       # пул соединений привязан к event loop теста
    invalidate_role_cache()


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
