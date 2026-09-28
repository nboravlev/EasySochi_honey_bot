"""Пользователь системы ↔ его аккаунты в платформах (Telegram, VK, …).

Везде внутри системы человек — это users.id. Платформенный ID нужен только адаптеру платформы:
найти пользователя по входящему сообщению и отправить ему ответ.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, UserIdentity
from domain.enums import Provider


async def find_user(session: AsyncSession, provider: Provider, external_id: str | int) -> User | None:
    return await session.scalar(
        select(User).join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.provider == provider, UserIdentity.external_id == str(external_id))
    )


async def get_or_create_user(
    session: AsyncSession,
    provider: Provider,
    external_id: str | int,
    *,
    username: str | None = None,
    is_bot: bool = False,
) -> tuple[User, bool]:
    """Пользователь по аккаунту платформы; нет — создаётся вместе с identity. Возвращает (user, создан)."""
    user = await find_user(session, provider, external_id)
    if user is not None:
        return user, False
    user = User(username=username, is_bot=is_bot)
    session.add(user)
    await session.flush()
    session.add(UserIdentity(user_id=user.id, provider=provider, external_id=str(external_id), username=username))
    await session.flush()
    return user, True


async def external_id(session: AsyncSession, user_id: int, provider: Provider) -> str | None:
    """ID человека в платформе (куда слать сообщения); None — если у него нет аккаунта в этой платформе."""
    return await session.scalar(
        select(UserIdentity.external_id)
        .where(UserIdentity.user_id == user_id, UserIdentity.provider == provider)
        .order_by(UserIdentity.id)
        .limit(1)
    )


async def find_by_username(session: AsyncSession, username: str) -> User | None:
    """По @username в любой платформе (сначала — в аккаунтах, затем в профиле)."""
    name = username.lstrip("@").lower()
    if not name:
        return None
    user = await session.scalar(
        select(User).join(UserIdentity, UserIdentity.user_id == User.id)
        .where(func.lower(UserIdentity.username) == name).limit(1)
    )
    return user or await session.scalar(select(User).where(func.lower(User.username) == name).limit(1))
