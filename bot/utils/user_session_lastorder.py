from sqlalchemy import select

from db.db_async import get_async_session
from db.models.users import User


async def get_user_by_tg_id(user_id: int):
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(User.tg_user_id == user_id)
        )
        return result.scalar_one_or_none()


async def create_user(tg_user, first_name=None, phone_number=None):
    """Регистрация. Если менеджер был назначен до первого /start, строка уже есть — дополняем её."""
    async with get_async_session() as session:
        user = await session.scalar(select(User).where(User.tg_user_id == tg_user.id))
        if user is None:
            user = User(tg_user_id=tg_user.id, is_bot=tg_user.is_bot)
            session.add(user)
        user.username = tg_user.username
        user.firstname = first_name
        user.phone_number = phone_number
        await session.commit()
        await session.refresh(user)
        return user
