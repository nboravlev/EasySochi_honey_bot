"""Пользователи и роли. Менеджер — users.role_id = MANAGER и users.shop_id (один магазин на человека)."""
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from db.db_async import get_async_session
from db.models import User
from domain.enums import Provider, Role
from services import identity

PROFILE_CACHE_TTL = 60  # сек; назначение/снятие менеджера сбрасывает кэш сразу


@dataclass(frozen=True)
class StaffProfile:
    role_id: int
    shop_id: int | None

    @property
    def is_manager(self) -> bool:
        return self.role_id == Role.MANAGER and self.shop_id is not None


_profile_cache: dict[int, tuple[StaffProfile | None, float]] = {}


def invalidate_profile_cache(user_id: int | None = None) -> None:
    if user_id is None:
        _profile_cache.clear()
    else:
        _profile_cache.pop(user_id, None)


async def get_staff_profile(user_id: int) -> StaffProfile | None:
    """Роль и магазин пользователя (с коротким кэшем: проверка прав идёт на каждое нажатие)."""
    cached = _profile_cache.get(user_id)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    async with get_async_session() as session:
        row = (await session.execute(select(User.role_id, User.shop_id).where(User.id == user_id))).first()
    profile = StaffProfile(role_id=row[0], shop_id=row[1]) if row else None
    _profile_cache[user_id] = (profile, time.monotonic() + PROFILE_CACHE_TTL)
    return profile


async def bootstrap_managers(session: AsyncSession, telegram_ids: set[int] | frozenset[int], shop_id: int | None) -> int:
    """Первый запуск: если в БД нет ни одного менеджера, MANAGER_LIST из .env становятся менеджерами витрины.

    Кто ещё не нажимал /start, создаётся по Telegram ID — имя подтянется при регистрации.
    """
    has_managers = await session.scalar(select(func.count()).select_from(User).where(User.role_id == Role.MANAGER))
    if has_managers or not telegram_ids or shop_id is None:
        return 0
    for tg_id in telegram_ids:
        user, _ = await identity.get_or_create_user(session, Provider.TELEGRAM, tg_id)
        user.role_id = Role.MANAGER
        user.shop_id = shop_id
    await session.flush()
    invalidate_profile_cache()
    return len(telegram_ids)


async def find_user(session: AsyncSession, ref: str) -> User | None:
    """Пользователь по «@username» или Telegram ID (как их знает владелец в Telegram)."""
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        return await identity.find_user(session, Provider.TELEGRAM, ref)
    return await identity.find_by_username(session, ref)


async def set_manager(session: AsyncSession, user: User, shop_id: int | None) -> None:
    """Назначить менеджером магазина (shop_id) или снять (None)."""
    user.role_id = Role.MANAGER if shop_id is not None else Role.USER
    user.shop_id = shop_id
    await session.flush()
    invalidate_profile_cache(user.id)


async def list_managers(session: AsyncSession, shop_id: int | None = None) -> list[User]:
    stmt = (
        select(User).options(selectinload(User.identities), selectinload(User.shop))
        .where(User.role_id == Role.MANAGER).order_by(User.shop_id, User.id)
    )
    if shop_id is not None:
        stmt = stmt.where(User.shop_id == shop_id)
    return list((await session.scalars(stmt)).all())


async def is_platform_owner(session: AsyncSession, user_id: int) -> bool:
    """Владелец платформы — человек с Telegram-аккаунтом OWNER_ID из .env."""
    owner_id = get_settings().owner_id
    if not owner_id:
        return False
    owner = await identity.find_user(session, Provider.TELEGRAM, owner_id)
    return owner is not None and owner.id == user_id
