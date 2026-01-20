from sqlalchemy import select, exists, or_, and_, update as sa_update
from datetime import datetime
from sqlalchemy.orm import selectinload
from db.db_async import get_async_session
from db.models.products import Product
from db.models.order_statuses import OrderStatus
from db.models.orders import Order

from telegram import Update

from telegram.ext import ContextTypes

from utils.logging_config import log_function_call, LogExecutionTime, get_logger

# Предположим, статус 5 = "pending", статус 6 = "confirmed"
ACTIVE_BOOKING_STATUSES = [5, 6]


logger = get_logger(__name__)

@log_function_call(action="Apartment_delete")
async def delete_apartment(apartment_id: int, tg_user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with get_async_session() as session:
        # Получаем квартиру с букингами
        result = await session.execute(
            select(Apartment)
            .options(selectinload(Apartment.booking))
            .where(Apartment.id == apartment_id)
        )
        apartment = result.scalar_one_or_none()

        if not apartment:
            await update.callback_query.message.reply_text("❌ Объект не найден.")
            return VIEW_OBJECTS

        # Проверка на активные бронирования
        has_active = any(b.status_id in ACTIVE_BOOKING_STATUSES for b in apartment.booking)

        if has_active:
            await update.callback_query.message.reply_text(
                "🚫 На данном объекте есть активные бронирования. "
                "Свяжитесь с администратором для удаления."
            )
            return REPORT_PROBLEM

        # Обновление полей
        await session.execute(
            update(Apartment)
            .where(Apartment.id == apartment_id)
            .values(
                is_active=False,
                updated_at=datetime.utcnow(),
                deleted_by=tg_user_id
            )
        )
        await session.commit()

        await update.callback_query.message.reply_text("✅ Объект успешно удалён.")
        return VIEW_OBJECTS
