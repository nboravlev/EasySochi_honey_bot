from sqlalchemy import select

from datetime import datetime

from db.db_async import get_async_session

from db.models.users import User
from db.models.sessions import Session

async def get_user_by_tg_id(user_id: int):
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(User.tg_user_id == user_id)
        )
        return result.scalar_one_or_none()


async def create_user(tg_user, first_name=None, phone_number=None):
    """Create new user in database"""
    async with get_async_session() as session:
        user = User(
            tg_user_id=tg_user.id,
            username=tg_user.username,
            firstname=first_name,
            phone_number=phone_number,
            is_bot=tg_user.is_bot,
            created_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

async def create_session(tg_user_id: int, role_id: int):
    """Create new session with role"""
    async with get_async_session() as session:
        new_session = Session(
            tg_user_id=tg_user_id,
            role_id=role_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(new_session)
        await session.commit()
        await session.refresh(new_session)
        return new_session

async def get_actual_session_by_tg_id(user_id: int, role_id: int):
        async with get_async_session() as session:
            # Проверяем, есть ли уже активная запись
            stmt = select(Session.id).where(
                Session.tg_user_id == user_id,
                Session.role_id == role_id,
                Session.sent_message.is_(False)
            )
            result = await session.execute(stmt)
            existing_session = result.scalars().first()
            return existing_session