from sqlalchemy import select, update, desc
from sqlalchemy.orm import joinedload

from datetime import datetime

from db.db_async import get_async_session

from db.models.users import User
from db.models.sessions import Session
from db.models.products import Product
from db.models.orders import Order
from db.models.images import Image
from db.models.order_statuses import OrderStatus
from db.models.product_sizes import  ProductSize
from utils.logging_config import log_db_select, log_db_insert

EXCEPT_STATUSES = [6,7,8,9]

"""
async def get_user_by_tg_id(tg_user_id: int):
    
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(User.tg_user_id == tg_user_id)
        )
        return result.scalars().first()
    """
@log_db_select(log_slow_only=True, slow_threshold=0.5)
async def get_user_by_tg_id(user_id: int):
    async with get_async_session() as session:
        print("DEBUG-session-created")
        result = await session.execute(
            select(User).where(User.tg_user_id == user_id)
        )
        print("DEBUG-query-executed")
        user = result.scalar_one_or_none()
        print(f"DEBUG-user-found: {user}")
        return user


@log_db_insert
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

@log_db_insert
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

@log_db_select(log_slow_only=True, slow_threshold=0.5)
async def get_last_order(tg_user_id: int) -> dict | None:
    """
    Получает последний активный заказ пользователя с расшифровкой напитка и размера.

    :param tg_user_id: Telegram ID пользователя
    :return: dict с полями заказа или None
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(Order)
            .options(
                joinedload(Order.product_size).joinedload(ProductSize.product),   # связь с Drink
                joinedload(Order.product_size).joinedload(ProductSize.sizes),   # связь с Size
                joinedload(Order.product_size).joinedload(ProductSize.product).joinload(Product.images)

            )
            .where(
                Order.tg_user_id == tg_user_id,
                Order.is_active == True,
                ~Order.status_id.in_(EXCEPT_STATUSES)  # фильтр на исключаемые статусы
            )
            .order_by(desc(Order.created_at))
            .limit(1)
        )
        order = result.scalars().first()

        if not order:
            return None

        product = order.product_size.product
        size = order.product_size.sizes
        media = None
        if product.images:
            media = product.images[0].tg_file_id

        return {
            "id": order.id,
            "product_size_id": order.product_size_id,
            "created_at": order.created_at,
            "product_name": product.name if product else "Неизвестно",
            "size": f"{size.name}кг" if size else " - ",
            "product_count": order.product_count,
            "total_price": float(order.total_price),
            "status_id": order.status_id,
            "image_file_id": media
        }
    
@log_db_select(log_slow_only=True, slow_threshold=0.5)
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