from sqlalchemy import select, exists, or_, and_
from datetime import datetime
from db.db_async import get_async_session
from bot.db.models.products import Product
from bot.db.models.order_statuses import OrderStatus
from bot.db.models.orders import Order
from utils.logging_config import (
    structured_logger, 
    log_db_select, 
    log_db_insert, 
    log_db_update,
    log_db_delete,
    LoggingContext,
    monitor_performance
)

async def get_apartments(
    check_in: datetime,
    check_out: datetime,
    session_id: int,
    tg_user_id: int,
    filters: dict
) -> tuple[list[int], list[Apartment], SearchSession]:

    type_ids = filters.get("type_ids")
    price = filters.get("price", {})

    async with get_async_session() as session:
        stmt = (select(Apartment).where(
                Apartment.is_draft.is_(False),
                Apartment.is_active.is_(True)
            ).order_by(
                Apartment.price.desc(),
                Apartment.created_at.desc()
            ))

        # ✅ Фильтр по типам
        if type_ids:
            stmt = stmt.where(Apartment.type_id.in_(type_ids))

        # ✅ Фильтр по цене
        if price:
            min_price = price.get("min")
            max_price = price.get("max")
            if min_price is not None:
                stmt = stmt.where(Apartment.price >= min_price)
            if max_price is not None:
                stmt = stmt.where(Apartment.price <= max_price)

        # ✅ Фильтр по датам: исключаем пересекающиеся брони
        if check_in and check_out:
            stmt = stmt.where(
                ~exists().where(
                    and_(
                        Booking.apartment_id == Apartment.id,
                        Booking.status_id.in_([5,6,7]),
                        or_(
                            and_(Booking.check_in <= check_in, Booking.check_out > check_in),
                            and_(Booking.check_in < check_out, Booking.check_out >= check_out),
                            and_(Booking.check_in >= check_in, Booking.check_out <= check_out)
                        )
                    )
                )
            )

        # ✅ Выполняем запрос
        result = await session.execute(stmt)
        apartments = result.scalars().all()
        apartment_ids = [apt.id for apt in apartments]

        # ✅ Логируем поиск
        new_search = SearchSession(
            session_id=session_id,
            tg_user_id=tg_user_id,
            filters=filters,  # JSON сохраняем как есть
            apartment_ids=apartment_ids,
            created_at=datetime.utcnow()
        )

        session.add(new_search)
        await session.commit()
        print(f"DUBUG_GET_APARTMENT: {apartment_ids},{apartments},{new_search.id}")
        return apartment_ids, apartments, new_search
