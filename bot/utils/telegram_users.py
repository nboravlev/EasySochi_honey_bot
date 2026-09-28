"""Пользователь системы по Telegram-аккаунту (для хендлеров бота)."""
from db.db_async import get_async_session
from db.models import User
from domain.enums import Provider
from services import identity
from utils.access import remember_user


async def get_user_by_tg_id(telegram_id: int) -> User | None:
    async with get_async_session() as session:
        return await identity.find_user(session, Provider.TELEGRAM, telegram_id)


async def register_telegram_user(tg_user, first_name: str | None = None, phone_number: str | None = None) -> User:
    """Регистрация из Telegram. Если человека уже создали (назначили менеджером до первого /start) —
    дополняем его профиль, а не создаём второго."""
    async with get_async_session() as session:
        user, _ = await identity.get_or_create_user(
            session, Provider.TELEGRAM, tg_user.id, username=tg_user.username, is_bot=tg_user.is_bot
        )
        user.username = tg_user.username
        user.firstname = first_name
        user.phone_number = phone_number
        await session.commit()
        await session.refresh(user)
    remember_user(tg_user.id, user.id)
    return user
