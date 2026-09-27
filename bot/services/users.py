"""Пользователи и роли. Роль менеджера хранится в users.role_id и назначается владельцем в боте."""
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.db_async import get_async_session
from db.models import User
from domain.enums import Role

ROLE_CACHE_TTL = 60  # сек; назначение/снятие менеджера сбрасывает кэш сразу
_role_cache: dict[int, tuple[int | None, float]] = {}


def invalidate_role_cache(tg_user_id: int | None = None) -> None:
    if tg_user_id is None:
        _role_cache.clear()
    else:
        _role_cache.pop(tg_user_id, None)


async def get_role(tg_user_id: int) -> int | None:
    """Роль пользователя из БД (с коротким кэшем: проверка прав идёт на каждое нажатие)."""
    cached = _role_cache.get(tg_user_id)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    async with get_async_session() as session:
        role = await session.scalar(select(User.role_id).where(User.tg_user_id == tg_user_id))
    _role_cache[tg_user_id] = (role, time.monotonic() + ROLE_CACHE_TTL)
    return role


async def bootstrap_managers(session: AsyncSession, tg_user_ids: frozenset[int] | set[int]) -> int:
    """Первый запуск: если в БД нет ни одного менеджера, назначает менеджерами MANAGER_LIST из .env.

    Пользователь, ещё не нажимавший /start, создаётся с одним tg_user_id — имя подтянется из профиля.
    Возвращает число назначенных.
    """
    has_managers = await session.scalar(select(func.count()).select_from(User).where(User.role_id == Role.MANAGER))
    if has_managers or not tg_user_ids:
        return 0
    existing = {
        u.tg_user_id: u
        for u in (await session.scalars(select(User).where(User.tg_user_id.in_(tg_user_ids)))).all()
    }
    for tg_user_id in tg_user_ids:
        user = existing.get(tg_user_id)
        if user is None:
            user = User(tg_user_id=tg_user_id, is_bot=False)
            session.add(user)
        user.role_id = Role.MANAGER
    await session.flush()
    invalidate_role_cache()
    return len(tg_user_ids)


async def find_user(session: AsyncSession, ref: str) -> User | None:
    """Пользователь по «@username», «username» или Telegram ID."""
    ref = ref.strip()
    if ref.lstrip("-").isdigit():
        return await session.scalar(select(User).where(User.tg_user_id == int(ref)))
    username = ref.lstrip("@")
    if not username:
        return None
    return await session.scalar(select(User).where(func.lower(User.username) == username.lower()))


async def set_manager(session: AsyncSession, user: User, is_manager: bool) -> None:
    user.role_id = Role.MANAGER if is_manager else Role.USER
    await session.flush()
    invalidate_role_cache(user.tg_user_id)


async def list_managers(session: AsyncSession) -> list[User]:
    result = await session.scalars(select(User).where(User.role_id == Role.MANAGER).order_by(User.id))
    return list(result.all())
